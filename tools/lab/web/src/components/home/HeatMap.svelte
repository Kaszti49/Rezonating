<script lang="ts">
  // Live heat map: which frequencies shake the floor, over the last seconds. Both geophones added, from the raw samples
  // in the browser. One hue, quiet recedes into the tile. A column with a lost sample stays empty.
  import { onMount } from 'svelte';
  import { app, streamFs } from '../../lib/store.svelte';
  import { fft } from '../../lib/home';

  const NFFT = 512;
  const COLS = 200;
  const HOP_S = 0.1;
  const F_MAX = 160;
  const RANGE_DB = 42; // quiet floor to full colour
  const PAD_L = 34;
  const PAD_B = 18;

  let canvas: HTMLCanvasElement;
  let box: HTMLDivElement;
  let ready = $state(false);
  let tip = $state<{ x: number; y: number; text: string } | null>(null);

  const re = new Float32Array(NFFT);
  const im = new Float32Array(NFFT);
  const win = Float32Array.from({ length: NFFT }, (_, i) => 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (NFFT - 1)));
  const cols: (Float32Array | null)[] = [];
  let bins = 0;
  let df = 1;
  let nextIndex = -1;
  let gen = -1;
  /** Quiet level per frequency (dB): a low percentile of the last columns, followed slowly. */
  let floor = new Float32Array(0);
  let floored = false;
  const off = document.createElement('canvas');

  // blue ramp, light to dark of the palette, reversed for a dark surface: near the surface = quiet
  const DARK: [number, number, number][] = [
    [20, 26, 34],
    [16, 66, 129],
    [42, 120, 214],
    [109, 167, 236],
    [205, 226, 251],
  ];
  const LIGHT: [number, number, number][] = [
    [255, 255, 255],
    [183, 211, 246],
    [85, 152, 231],
    [28, 92, 171],
    [13, 54, 107],
  ];

  function ramp(t: number, stops: [number, number, number][]): [number, number, number] {
    const x = Math.min(0.9999, Math.max(0, t)) * (stops.length - 1);
    const i = Math.floor(x);
    const f = x - i;
    const a = stops[i];
    const b = stops[i + 1];
    return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
  }

  function rawStream(): number | null {
    return app.hello?.streams.find((s) => s.name === 'adc_raw')?.id ?? null;
  }

  function ingest(): boolean {
    const id = rawStream();
    const ring = id === null ? undefined : app.rings.get(id);
    if (id === null || !ring || !ring.hasData) return false;
    const fs = streamFs(id);
    const hop = Math.max(1, Math.round(HOP_S * fs));
    df = fs / NFFT;
    bins = Math.min(NFFT / 2, Math.ceil(F_MAX / df));
    if (ring.generation !== gen) {
      gen = ring.generation;
      cols.length = 0;
      nextIndex = -1;
      floored = false;
    }
    if (nextIndex < 0 || ring.head - nextIndex > COLS * hop) nextIndex = Math.max(ring.lo + NFFT, ring.head - COLS * hop);
    let added = false;
    while (nextIndex <= ring.head && nextIndex - NFFT >= ring.lo) {
      cols.push(column(ring.data, ring.cap, nextIndex - NFFT, Math.min(2, ring.nCh)));
      if (cols.length > COLS) cols.shift();
      nextIndex += hop;
      added = true;
    }
    return added;
  }

  function column(data: Float32Array[], cap: number, first: number, nCh: number): Float32Array | null {
    const out = new Float32Array(bins);
    for (let c = 0; c < nCh; c++) {
      const d = data[c];
      let mean = 0;
      for (let i = 0; i < NFFT; i++) {
        const v = d[(first + i) % cap];
        if (v !== v) return null;
        mean += v;
      }
      mean /= NFFT;
      for (let i = 0; i < NFFT; i++) {
        re[i] = (d[(first + i) % cap] - mean) * win[i];
        im[i] = 0;
      }
      fft(re, im);
      for (let b = 0; b < bins; b++) out[b] += re[b] * re[b] + im[b] * im[b];
    }
    for (let b = 0; b < bins; b++) out[b] = 10 * Math.log10(out[b] + 1);
    return out;
  }

  function trackFloor(): void {
    const held = cols.filter((c): c is Float32Array => c !== null);
    if (held.length < 8) return;
    if (floor.length !== bins) {
      floor = new Float32Array(bins);
      floored = false;
    }
    const v = new Float32Array(held.length);
    for (let b = 0; b < bins; b++) {
      for (let i = 0; i < held.length; i++) v[i] = held[i][b];
      v.sort();
      const f = v[Math.floor(v.length * 0.2)];
      floor[b] = floored ? floor[b] + 0.1 * (f - floor[b]) : f;
    }
    floored = true;
  }

  function draw(): void {
    if (!canvas || !box) return;
    const dpr = window.devicePixelRatio || 1;
    const w = box.clientWidth;
    const h = box.clientHeight;
    if (w < 60 || h < 40) return;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
    }
    const g = canvas.getContext('2d');
    if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    const pw = w - PAD_L - 4;
    const ph = h - PAD_B - 4;
    const cs = getComputedStyle(document.documentElement);
    g.fillStyle = cs.getPropertyValue('--muted');
    g.font = '10.5px system-ui, sans-serif';
    g.textBaseline = 'middle';
    g.textAlign = 'right';
    for (const f of [0, 40, 80, 120, 160]) g.fillText(String(f), PAD_L - 6, Math.max(9, 4 + ph * (1 - f / F_MAX)));
    g.textAlign = 'left';
    g.fillText('20 s ago', PAD_L, h - 8);
    g.textAlign = 'right';
    g.fillText('now', w - 4, h - 8);
    if (!cols.length || bins === 0 || !floored) return;
    const stops = app.theme === 'light' ? LIGHT : DARK;
    off.width = COLS;
    off.height = bins;
    const og = off.getContext('2d');
    if (!og) return;
    const img = og.createImageData(COLS, bins);
    const x0 = COLS - cols.length;
    for (let x = 0; x < cols.length; x++) {
      const c = cols[x];
      if (!c) continue;
      for (let b = 0; b < bins; b++) {
        const [r, gg, bl] = ramp((c[b] - floor[b]) / RANGE_DB, stops);
        const o = ((bins - 1 - b) * COLS + x0 + x) * 4;
        img.data[o] = r;
        img.data[o + 1] = gg;
        img.data[o + 2] = bl;
        img.data[o + 3] = 255;
      }
    }
    og.putImageData(img, 0, 0);
    g.imageSmoothingEnabled = true;
    g.imageSmoothingQuality = 'high';
    g.save();
    g.beginPath();
    g.roundRect(PAD_L, 4, pw, ph, 8);
    g.clip();
    g.drawImage(off, PAD_L, 4, pw, ph);
    g.restore();
  }

  function hover(e: PointerEvent): void {
    const r = box.getBoundingClientRect();
    const x = e.clientX - r.left;
    const y = e.clientY - r.top;
    const pw = r.width - PAD_L - 4;
    const ph = r.height - PAD_B - 4;
    const u = (x - PAD_L) / pw;
    const v = 1 - (y - 4) / ph;
    const ci = Math.floor(u * COLS) - (COLS - cols.length);
    const bi = Math.min(bins - 1, Math.floor((v * F_MAX) / df));
    const c = cols[ci];
    if (u < 0 || u > 1 || v < 0 || v > 1 || !c || bi < 0) {
      tip = null;
      return;
    }
    const db = Math.max(0, c[bi] - floor[bi]);
    const ago = ((1 - u) * COLS * HOP_S).toFixed(1);
    tip = { x: Math.min(x + 12, r.width - 150), y: Math.max(4, y - 34), text: `${Math.round(bi * df)} Hz · ${ago} s ago · ${db.toFixed(0)} dB over quiet` };
  }

  onMount(() => {
    let raf = 0;
    let last = 0;
    const loop = (t: number): void => {
      if (t - last > 60) {
        last = t;
        const added = ingest();
        if (added) {
          trackFloor();
          ready = floored;
        }
        draw();
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  });
</script>

<div class="heat" bind:this={box} onpointermove={hover} onpointerleave={() => (tip = null)} role="img" aria-label="Heat map of vibration: frequency over the last 20 seconds">
  <canvas bind:this={canvas}></canvas>
  {#if !ready}<div class="skel" aria-hidden="true"></div>{/if}
  {#if tip}<div class="tip" style:left={`${tip.x}px`} style:top={`${tip.y}px`}>{tip.text}</div>{/if}
</div>

<style>
  .heat {
    position: relative;
    width: 100%;
    height: 100%;
    min-height: 120px;
  }
  canvas {
    position: absolute;
    inset: 0;
  }
  .skel {
    position: absolute;
    inset: 4px 4px 18px 34px;
    border-radius: 8px;
  }
</style>
