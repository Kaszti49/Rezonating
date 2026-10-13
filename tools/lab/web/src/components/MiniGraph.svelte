<script lang="ts">
  import type uPlot from 'uplot';
  import Plot from './Plot.svelte';
  import { app } from '../lib/store.svelte';
  import { axisBase, cssVar, readPalette } from '../lib/plotopts';

  interface SeriesSpec {
    label: string;
    cssVar: string;
    fallback: string;
  }
  interface Props {
    title: string;
    yLabel: string;
    series: SeriesSpec[];
    /** The y arrays, one per series, aligned with app.health.t. */
    pick: () => (number | null)[][];
    digits?: number;
  }
  let { title, yLabel, series, pick, digits = 1 }: Props = $props();

  let plot: ReturnType<typeof Plot> | undefined = $state();
  let lastText = $state<string[]>([]);

  const opts = $derived.by(() => {
    void app.theme;
    const pal = readPalette();
    const s: uPlot.Series[] = [{}];
    for (const sp of series) {
      s.push({
        label: sp.label,
        stroke: cssVar(sp.cssVar, sp.fallback),
        width: 1.4,
        points: { show: false },
        spanGaps: false,
      });
    }
    return {
      series: s,
      legend: { show: false },
      cursor: { drag: { x: false, y: false }, points: { show: false } },
      scales: { x: { time: false } },
      axes: [{ ...axisBase(pal, 's ago'), size: 34 }, { ...axisBase(pal, yLabel), size: 58 }],
    } as Omit<uPlot.Options, 'width' | 'height'>;
  });

  $effect(() => {
    void app.healthVersion;
    void opts;
    const t = app.health.t;
    if (t.length === 0) {
      plot?.setData([[], ...series.map(() => [])] as unknown as uPlot.AlignedData, true);
      lastText = [];
      return;
    }
    const lastT = t[t.length - 1];
    const x = t.map((v) => v - lastT);
    const ys = pick();
    plot?.setData([x, ...ys] as unknown as uPlot.AlignedData, true);
    lastText = ys.map((a) => {
      const v = a[a.length - 1];
      return v === null || v === undefined ? '—' : v.toFixed(digits);
    });
  });
</script>

<section class="card">
  <header>
    <h2>{title}</h2>
    <span class="grow"></span>
    <span class="legend num" style="margin:0">
      {#each series as sp, i (sp.label)}
        <span class="ch">
          <span class="swatch" style="background:var({sp.cssVar})"></span>
          {sp.label}
          <strong>{lastText[i] ?? '—'}</strong>
        </span>
      {/each}
    </span>
  </header>
  <Plot bind:this={plot} options={opts} height={150} />
</section>
