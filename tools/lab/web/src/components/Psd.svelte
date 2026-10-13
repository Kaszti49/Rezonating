<script lang="ts">
  import type uPlot from 'uplot';
  import Plot from './Plot.svelte';
  import { api, isAbort } from '../lib/api';
  import { app, chName, effUnit, nativeUnit } from '../lib/store.svelte';
  import { axisBase, readPalette } from '../lib/plotopts';
  import { fmtFixed } from '../lib/format';
  import type { HelloStream } from '../lib/types';

  interface Props {
    stream: HelloStream;
    frozen: number | null;
    backS: number;
  }
  let { stream, frozen, backS }: Props = $props();

  let plot: ReturnType<typeof Plot> | undefined = $state();
  let err = $state('');
  let peaks = $state<(number | null)[]>([]);
  let info = $state('');

  const unit0 = $derived(effUnit(nativeUnit(stream.id, 0), app.units));
  const unitLabel = $derived(unit0 ?? 'counts');

  const opts = $derived.by(() => {
    void app.theme; // rebuild with the new axis colours when the theme changes
    const pal = readPalette();
    const series: uPlot.Series[] = [{}];
    for (let c = 0; c < stream.n_ch; c++) {
      series.push({
        label: chName(stream.name, c),
        stroke: app.colors[c % app.colors.length],
        width: 1.3,
        points: { show: false },
        spanGaps: false,
      });
    }
    return {
      series,
      legend: { show: false },
      cursor: { drag: { x: false, y: false }, points: { show: false } },
      scales: { x: { time: false }, y: { auto: true } },
      axes: [{ ...axisBase(pal, 'Hz'), size: 34 }, { ...axisBase(pal, `dB re ${unitLabel}²/Hz`), size: 64 }],
    } as Omit<uPlot.Options, 'width' | 'height'>;
  });

  async function load(f: number | null, b: number, w: number, units: string, signal: AbortSignal): Promise<void> {
    try {
      const fs = app.fs.get(stream.id) ?? stream.nominal_hz;
      const end = f === null ? undefined : Math.max(1, Math.round(f - b * fs));
      const r = await api.psd({ stream: stream.id, window_s: Math.max(2, w), nperseg: 1024, end }, signal);
      const cfg = app.config?.streams.find((s) => s.id === stream.id);
      const x = r.freq_hz;
      const cols: (number | null)[][] = [];
      const pk: (number | null)[] = [];
      for (let c = 0; c < stream.n_ch; c++) {
        const p = r.psd[c];
        const ch = cfg?.channels[c];
        // Native unit is what the server computed in; counts = divide by scale.
        const toCounts = units === 'counts' && ch && ch.scale > 0 ? 1 / (ch.scale * ch.scale) : 1;
        const out: (number | null)[] = new Array<number | null>(x.length).fill(null);
        let best = -Infinity;
        let bestF: number | null = null;
        if (p) {
          for (let i = 0; i < x.length; i++) {
            const v = p[i];
            if (v !== null && v !== undefined && v > 0) {
              const db = 10 * Math.log10(v * toCounts);
              out[i] = db;
              if (i >= 2 && db > best) {
                best = db;
                bestF = x[i];
              }
            }
          }
        }
        cols.push(out);
        pk.push(bestF);
      }
      peaks = pk;
      info = `${r.n_segments} segments, ${fmtFixed(r.fs_hz / r.nperseg, 2)} Hz/bin`;
      err = '';
      plot?.setData([x, ...cols] as unknown as uPlot.AlignedData, true);
    } catch (e) {
      if (!isAbort(e)) err = e instanceof Error ? e.message : String(e);
    }
  }

  $effect(() => {
    const f = frozen;
    const b = backS;
    const w = app.windowS;
    // The unit choice changes the scaling only; a counts request still reads native units from the server.
    const u = unit0 === null || unit0 === 'counts' ? 'counts' : 'native';
    void app.theme;
    const ctl = new AbortController();
    let timer: number | undefined;
    const run = () => void load(f, b, w, u, ctl.signal);
    const first = window.setTimeout(run, f === null ? 0 : 80);
    if (f === null) timer = window.setInterval(() => !document.hidden && run(), 1000);
    return () => {
      ctl.abort();
      window.clearTimeout(first);
      window.clearInterval(timer);
    };
  });
</script>

<section class="card">
  <header>
    <h2>PSD · {stream.name}</h2>
    <span class="muted num">{info}</span>
    <span class="grow"></span>
    <span class="legend num" style="margin:0">
      {#each peaks as pk, c (c)}
        <span class="ch">
          <span class="swatch" style="background:{app.colors[c % app.colors.length]}"></span>
          {chName(stream.name, c)} peak {fmtFixed(pk, 1, ' Hz')}
        </span>
      {/each}
    </span>
  </header>
  <Plot bind:this={plot} options={opts} height={250} />
  {#if err}<div class="inline-err">{err}</div>{/if}
</section>
