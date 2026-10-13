<script lang="ts">
  import type uPlot from 'uplot';
  import { onMount, untrack } from 'svelte';
  import Plot from './Plot.svelte';
  import { api, isAbort } from '../lib/api';
  import { app, chName, effUnit, nativeUnit, streamFs, toDisplay, unitFactor } from '../lib/store.svelte';
  import { buildFromServer, buildLive, histFrom, ScopeData, type HistEnvelope, type LiveRing } from '../lib/ring';
  import { axisBase, hexAlpha, readPalette } from '../lib/plotopts';
  import { fmtFixed, fmtInt, fmtPct, fmtVal } from '../lib/format';
  import type { EnvelopeResponse, HelloStream, Levels } from '../lib/types';

  interface Props {
    stream: HelloStream;
    /** Sample index of the pause point, or null while live. */
    frozen: number | null;
    /** Seconds scrolled back from the pause point. */
    backS: number;
  }
  let { stream, frozen, backS }: Props = $props();

  const id = untrack(() => stream.id);
  const nCh = untrack(() => stream.n_ch);
  const data = new ScopeData(nCh);

  let plot: ReturnType<typeof Plot> | undefined = $state();
  let hist: HistEnvelope | null = null;
  let histGen = -1;
  let histStamp = 0;
  let server: EnvelopeResponse | null = null;
  let serverStamp = 0;
  let fetchErr = $state('');
  /** Levels of the visible window while paused (live levels come from the status event). */
  let pausedLevels = $state.raw<Levels[] | null>(null);
  let ctl: AbortController | null = null;
  const ks: number[] = new Array<number>(nCh).fill(1);

  const st = $derived(app.status?.streams.find((s) => s.id === id));
  const unit0 = $derived(effUnit(nativeUnit(id, 0), app.units));
  const unitLabel = $derived(unit0 ?? 'counts');

  const opts = $derived.by(() => {
    const pal = readPalette();
    const colors = app.colors;
    const label = unitLabel;
    const series: uPlot.Series[] = [{}];
    const bands: uPlot.Band[] = [];
    for (let c = 0; c < nCh; c++) {
      const col = colors[c % colors.length];
      const base: uPlot.Series = { stroke: col, width: 1, points: { show: false }, spanGaps: false };
      series.push({ ...base, label: `${chName(stream.name, c)} max` }, { ...base, label: `${chName(stream.name, c)} min` });
      bands.push({ series: [1 + 2 * c, 2 + 2 * c], fill: hexAlpha(col, 0.28) });
    }
    return {
      series,
      bands,
      legend: { show: false },
      cursor: { drag: { x: false, y: false }, points: { show: false } },
      scales: { x: { time: false, range: (): [number, number] => [-app.windowS, 0] } },
      axes: [{ ...axisBase(pal, 's'), size: 34 }, { ...axisBase(pal, label, label === 'counts' ? undefined : label), size: 72 }],
      hooks: { draw: [(u: uPlot) => drawGaps(u, pal.err)] },
    } as Omit<uPlot.Options, 'width' | 'height'>;
  });

  function drawGaps(u: uPlot, err: string): void {
    const n = data.n;
    if (n === 0) return;
    const ctx = u.ctx;
    const { left, top, width, height } = u.bbox;
    const dpr = window.devicePixelRatio || 1;
    const x0 = u.valToPos(data.x[0], 'x', true);
    const x1 = u.valToPos(data.x[n - 1], 'x', true);
    const colW = n > 1 ? Math.max(1, (x1 - x0) / (n - 1)) : 1;
    ctx.save();
    ctx.beginPath();
    ctx.rect(left, top, width, height);
    ctx.clip();
    for (let i = 0; i < n; i++) {
      const f = data.flag[i];
      if (f === 0) continue;
      const x = u.valToPos(data.x[i], 'x', true);
      if (f === 1) {
        ctx.fillStyle = hexAlpha(err, 0.2);
        ctx.fillRect(x, top, colW, height);
      } else {
        ctx.fillStyle = hexAlpha(err, 0.9);
        ctx.fillRect(x, top + height - 5 * dpr, colW, 5 * dpr);
      }
    }
    ctx.restore();
  }

  async function fetchHist(ring: LiveRing): Promise<void> {
    const gen = ring.generation;
    if (ring.base < 1) return;
    try {
      const r = await api.envelope({ stream: id, window_s: 60, columns: 1500, end: ring.base });
      if (ring.generation === gen) {
        hist = histFrom(r);
        histStamp++;
      }
    } catch {
      /* history is a nicety; the live part still draws */
    }
  }

  async function fetchServer(f: number, b: number, w: number): Promise<void> {
    ctl?.abort();
    const c = new AbortController();
    ctl = c;
    const cols = Math.min(4000, Math.max(100, plot?.getWidth() ?? 800));
    const end = Math.max(1, Math.round(f - b * streamFs(id)));
    try {
      const [r, lvl] = await Promise.all([
        api.envelope({ stream: id, window_s: w, columns: cols, end }, c.signal),
        api.levels({ stream: id, window_s: w, end }, c.signal),
      ]);
      server = r;
      pausedLevels = lvl.channels;
      serverStamp++;
      fetchErr = '';
    } catch (e) {
      if (!isAbort(e)) fetchErr = e instanceof Error ? e.message : String(e);
    }
  }

  $effect(() => {
    const f = frozen;
    const b = backS;
    const w = app.windowS;
    if (f === null) {
      ctl?.abort();
      server = null;
      pausedLevels = null;
      serverStamp++;
      fetchErr = '';
      return;
    }
    const t = window.setTimeout(() => void fetchServer(f, b, w), 80);
    return () => window.clearTimeout(t);
  });

  const sig = new Float64Array(10).fill(-1);
  const now = new Float64Array(10);

  onMount(() => {
    let raf = 0;
    let last = 0;
    const frame = (ts: number) => {
      raf = requestAnimationFrame(frame);
      if (document.hidden || ts - last < 33 || !plot) return;
      last = ts;
      const ring = app.rings.get(id);
      if (frozen === null && ring && ring.hasData && histGen !== ring.generation) {
        histGen = ring.generation;
        hist = null;
        histStamp++;
        void fetchHist(ring);
      }
      const unitsIdx = app.units === 'counts' ? 0 : app.units === 'V' ? 1 : 2;
      now[0] = frozen === null ? (ring ? ring.version : -1) : -2;
      now[1] = app.windowS;
      now[2] = unitsIdx;
      now[3] = app.config?.t ?? 0;
      now[4] = plot.getWidth();
      now[5] = histStamp;
      now[6] = serverStamp;
      now[7] = frozen === null ? 0 : 1;
      now[8] = streamFs(id);
      now[9] = app.theme === 'dark' ? 0 : 1;
      let same = true;
      for (let i = 0; i < now.length; i++) {
        if (now[i] !== sig[i]) {
          same = false;
          sig[i] = now[i];
        }
      }
      if (same) return;
      for (let c = 0; c < nCh; c++) ks[c] = unitFactor(id, c, app.units);
      if (frozen === null) {
        if (ring && ring.hasData) buildLive(data, ring, app.windowS, streamFs(id), now[4], ks, hist);
        else {
          data.clear();
          data.finish();
        }
      } else if (server) {
        buildFromServer(data, server, ks);
      } else {
        data.clear();
        data.finish();
      }
      plot.setData(data.plot as unknown as uPlot.AlignedData, true);
    };
    raf = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(raf);
      ctl?.abort();
    };
  });

  function lv(ch: number): Levels | null {
    return (frozen !== null ? pausedLevels?.[ch] : st?.levels?.[ch]) ?? null;
  }
</script>

<section class="card">
  <header>
    <h2>{stream.name}</h2>
    <span class="num muted">
      {stream.n_ch} ch · nominal {fmtInt(stream.nominal_hz)} Hz · measured
      {fmtFixed(st?.rate_hz_fit ?? st?.rate_hz_status, 1, ' Hz')} ({fmtPct(st?.offset_pct_fit ?? st?.offset_pct_status)})
    </span>
    <span class="grow"></span>
    {#if app.units !== 'counts' && unit0 === null}
      <span class="chip warn" title="This stream is in {nativeUnit(id, 0)}; showing counts">{app.units} n/a: showing counts</span>
    {/if}
    <span class="chip {st?.running ? 'ok' : ''}">{st?.running ? 'running' : 'stopped'}</span>
  </header>
  <Plot bind:this={plot} options={opts} height={230} />
  {#if fetchErr}<div class="inline-err">{fetchErr}</div>{/if}
  <div class="legend num">
    <span class="muted">{frozen !== null ? `levels over the ${app.windowS} s window` : 'levels, last 1 s'}</span>
    {#each { length: nCh } as _, c (c)}
      {@const l = lv(c)}
      {@const u = effUnit(nativeUnit(id, c), app.units)}
      <div class="ch">
        <span class="swatch" style="background:{app.colors[c % app.colors.length]}"></span>
        <strong>{chName(stream.name, c)}</strong>
        <span class="muted">RMS</span>
        <span>{fmtVal(toDisplay(id, c, l?.rms, app.units), u)}</span>
        <span class="muted">peak</span>
        <span>{fmtVal(toDisplay(id, c, l?.peak, app.units), u)}</span>
        <span class="clip" class:on={(l?.clipped ?? 0) > 0} title="samples at full scale in the last second">
          {(l?.clipped ?? 0) > 0 ? `CLIP ${l?.clipped}` : 'no clip'}
        </span>
      </div>
    {/each}
  </div>
</section>
