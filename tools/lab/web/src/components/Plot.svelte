<script lang="ts">
  import uPlot from 'uplot';
  import 'uplot/dist/uPlot.min.css';
  import { onMount } from 'svelte';

  interface Props {
    options: Omit<uPlot.Options, 'width' | 'height'>;
    height?: number;
  }
  let { options, height = 200 }: Props = $props();

  let el: HTMLDivElement | undefined = $state();
  let u: uPlot | null = null;
  let lastData: uPlot.AlignedData | null = null;

  export function setData(d: uPlot.AlignedData, reset = true): void {
    lastData = d;
    u?.setData(d, reset);
  }
  export function redraw(): void {
    u?.redraw(false, false);
  }
  export function getWidth(): number {
    return el?.clientWidth ?? 600;
  }

  $effect(() => {
    const host = el;
    const o = options;
    const h = height;
    if (!host) return;
    const empty = o.series.map(() => []) as unknown as uPlot.AlignedData;
    const plot = new uPlot({ ...o, width: Math.max(120, host.clientWidth), height: h }, lastData ?? empty, host);
    u = plot;
    return () => {
      plot.destroy();
      if (u === plot) u = null;
    };
  });

  onMount(() => {
    const ro = new ResizeObserver(() => {
      if (u && el) u.setSize({ width: Math.max(120, el.clientWidth), height });
    });
    if (el) ro.observe(el);
    return () => ro.disconnect();
  });
</script>

<div class="plot" bind:this={el}></div>
