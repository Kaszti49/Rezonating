<script lang="ts">
  import { onMount } from 'svelte';
  import { api, isAbort } from '../lib/api';
  import { app, chName } from '../lib/store.svelte';
  import { fmtFixed } from '../lib/format';
  import type { HelloStream, SpectrogramResponse } from '../lib/types';

  interface Props {
    stream: HelloStream;
    channel: number;
    frozen: number | null;
    backS: number;
  }
  let { stream, channel, frozen, backS }: Props = $props();

  const MAX_COLS = 300;
  const NFFT = 256;

  let canvas: HTMLCanvasElement | undefined = $state();
  let err = $state('');
  let range = $state({ lo: 0, hi: 0 });
  let freqMax = $state(0);
  let dbUnits = $state('');

  // Plain (non-reactive) data: updated once per second, drawn on demand.
  let cols: (Float32Array | null)[] = [];
  let centers: number[] = [];
  let hop = 0;
  let nbins = 0;
  let epoch = -1;
  let keep = MAX_COLS;
  let vLo = Number.NaN;
  let vHi = Number.NaN;
  const off = document.createElement('canvas');
  let img: ImageData | null = null;
  const scratch = new Float32Array(6000);

  // Inferno-like colour map, 256 entries.
  const LUT = (() => {
    const stops: [number, number, number, number][] = [
      [0, 0, 0, 4],
      [0.25, 66, 10, 104],
      [0.5, 147, 38, 103],
      [0.75, 221, 81, 58],
      [0.9, 252, 165, 10],
      [1, 252, 255, 164],
    ];
    const lut = new Uint8ClampedArray(256 * 3);
    for (let i = 0; i < 256; i++) {
      const t = i / 255;
      let k = 1;
      while (k < stops.length - 1 && stops[k][0] < t) k++;
      const a = stops[k - 1];
      const b = stops[k];
      const f = (t - a[0]) / (b[0] - a[0]);
      for (let c = 0; c < 3; c++) lut[i * 3 + c] = a[c + 1] + (b[c + 1] - a[c + 1]) * f;
    }
    return lut;
  })();

  function toRow(src: (number | null)[] | null): Float32Array | null {
    if (!src) return null;
    const a = new Float32Array(src.length);
    for (let i = 0; i < src.length; i++) {
      const v = src[i];
      a[i] = v === null ? Number.NaN : v;
    }
    return a;
  }

  function ingest(r: SpectrogramResponse, replace: boolean, w: number): void {
    if (replace || r.epoch !== epoch || r.hop !== hop) {
      cols = [];
      centers = [];
    }
    epoch = r.epoch;
    hop = r.hop;
    nbins = r.freq_hz.length;
    freqMax = r.freq_hz[r.freq_hz.length - 1] ?? 0;
    dbUnits = r.db_units;
    keep = Math.max(1, Math.min(MAX_COLS, Math.ceil((w * r.fs_hz) / r.hop)));
    const last = centers.length ? centers[centers.length - 1] : -Infinity;
    for (let i = 0; i < r.center_index.length; i++) {
      if (r.center_index[i] <= last) continue;
      centers.push(r.center_index[i]);
      cols.push(toRow(r.db[i]));
    }
    if (cols.length > keep) {
      cols.splice(0, cols.length - keep);
      centers.splice(0, centers.length - keep);
    }
  }

  function draw(): void {
    const cv = canvas;
    if (!cv) return;
    const dpr = window.devicePixelRatio || 1;
    const W = Math.max(1, Math.floor(cv.clientWidth * dpr));
    const H = Math.max(1, Math.floor(cv.clientHeight * dpr));
    if (cv.width !== W) cv.width = W;
    if (cv.height !== H) cv.height = H;
    const ctx = cv.getContext('2d');
    if (!ctx) return;
    ctx.fillStyle = '#05080c';
    ctx.fillRect(0, 0, W, H);
    const n = cols.length;
    if (n === 0 || nbins === 0) return;
    // Colour range from the 2nd and 99.5th percentile of a sample of the visible values.
    let m = 0;
    const total = n * nbins;
    const stride = Math.max(1, Math.floor(total / scratch.length));
    for (let j = 0; j < total && m < scratch.length; j += stride) {
      const col = cols[Math.floor(j / nbins)];
      const v = col ? col[j % nbins] : Number.NaN;
      if (v === v) scratch[m++] = v;
    }
    if (m > 10) {
      const s = scratch.subarray(0, m).sort();
      const lo = s[Math.floor(m * 0.02)];
      const hi = Math.max(s[Math.floor(m * 0.995)], lo + 6);
      vLo = vLo === vLo ? vLo + 0.3 * (lo - vLo) : lo;
      vHi = vHi === vHi ? vHi + 0.3 * (hi - vHi) : hi;
      range = { lo: vLo, hi: vHi };
    }
    if (!(vHi > vLo)) return;
    if (off.width !== n) off.width = n;
    if (off.height !== nbins) off.height = nbins;
    const octx = off.getContext('2d');
    if (!octx) return;
    if (!img || img.width !== n || img.height !== nbins) img = octx.createImageData(n, nbins);
    const px = img.data;
    const scale = 255 / (vHi - vLo);
    for (let x = 0; x < n; x++) {
      const col = cols[x];
      for (let b = 0; b < nbins; b++) {
        const o = ((nbins - 1 - b) * n + x) * 4;
        const v = col ? col[b] : Number.NaN;
        if (v === v) {
          let k = Math.round((v - vLo) * scale);
          k = k < 0 ? 0 : k > 255 ? 255 : k;
          px[o] = LUT[k * 3];
          px[o + 1] = LUT[k * 3 + 1];
          px[o + 2] = LUT[k * 3 + 2];
        } else {
          px[o] = 30;
          px[o + 1] = 34;
          px[o + 2] = 40;
        }
        px[o + 3] = 255;
      }
    }
    octx.putImageData(img, 0, 0);
    const dw = (W * n) / keep;
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(off, 0, 0, n, nbins, W - dw, 0, dw, H);
  }

  async function fetchCols(full: boolean, f: number | null, b: number, w: number, signal: AbortSignal): Promise<void> {
    const fs = app.fs.get(stream.id) ?? stream.nominal_hz;
    const end = f === null ? undefined : Math.max(1, Math.round(f - b * fs));
    try {
      const r = await api.spectrogram(
        {
          stream: stream.id,
          channel,
          window_s: w,
          nfft: NFFT,
          max_columns: MAX_COLS,
          end,
          ...(full || hop === 0 ? {} : { hop, since: centers.length ? centers[centers.length - 1] : undefined }),
        },
        signal,
      );
      if (signal.aborted) return;
      ingest(r, full, w);
      err = '';
      draw();
    } catch (e) {
      if (!isAbort(e)) err = e instanceof Error ? e.message : String(e);
    }
  }

  $effect(() => {
    const f = frozen;
    const b = backS;
    const w = Math.max(2, app.windowS);
    void stream.id;
    void channel;
    cols = [];
    centers = [];
    hop = 0;
    epoch = -1;
    vLo = Number.NaN;
    vHi = Number.NaN;
    const ctl = new AbortController();
    const first = window.setTimeout(() => void fetchCols(true, f, b, w, ctl.signal), f === null ? 0 : 80);
    let timer: number | undefined;
    if (f === null) timer = window.setInterval(() => !document.hidden && void fetchCols(false, f, b, w, ctl.signal), 1000);
    return () => {
      ctl.abort();
      window.clearTimeout(first);
      window.clearInterval(timer);
    };
  });

  onMount(() => {
    const ro = new ResizeObserver(() => draw());
    if (canvas) ro.observe(canvas);
    return () => ro.disconnect();
  });
</script>

<section class="card">
  <header>
    <h2>Spectrogram · {stream.name} {chName(stream.name, channel)}</h2>
    <span class="muted num">
      {NFFT} pt FFT · {dbUnits || '—'} · colour {fmtFixed(range.lo, 0)} to {fmtFixed(range.hi, 0)} dB
    </span>
  </header>
  <div class="spec" style="height:250px">
    <canvas bind:this={canvas}></canvas>
    <span class="lab" style="left:6px;top:3px">{fmtFixed(freqMax, 0, ' Hz')}</span>
    <span class="lab" style="left:6px;top:50%">{fmtFixed(freqMax / 2, 0, ' Hz')}</span>
    <span class="lab" style="left:6px;bottom:3px">0 Hz</span>
    <span class="lab" style="right:6px;bottom:3px">now</span>
    <span class="lab" style="left:70px;bottom:3px">&minus;{Math.max(2, app.windowS)} s</span>
  </div>
  {#if err}<div class="inline-err">{err}</div>{/if}
</section>
