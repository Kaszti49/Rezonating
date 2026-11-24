<script lang="ts">
  // Live vibration as one line whose tone follows its strength: rms of both geophones per 50 ms, on a log scale, drawn as
  // a smooth SVG path that grows in when the page opens. A bucket with a lost sample breaks the line.
  import { onMount } from 'svelte';
  import { Tween } from 'svelte/motion';
  import { cubicOut } from 'svelte/easing';
  import { app, streamFs } from '../../lib/store.svelte';
  import { reducedMotion, smoothPath, type Pt } from '../../lib/home';

  const WINDOW_S = 12;
  const BUCKET_S = 0.05;
  const PAD_L = 48;
  const PAD_R = 16;
  const PAD_T = 10;
  const PAD_B = 18;
  const LO_UV = 10;
  const HI_UV = 100000;

  let box: HTMLDivElement;
  let w = $state(600);
  let h = $state(160);
  let runs = $state.raw<{ line: string; area: string }[]>([]);
  let end = $state.raw<{ x: number; y: number; uv: number } | null>(null);
  let ready = $state(false);
  let hover = $state<{ x: number; y: number; uv: number; ago: number } | null>(null);
  const grow = new Tween(0, { duration: reducedMotion() ? 0 : 1400, easing: cubicOut });

  let values: { ago: number; uv: number | null }[] = [];

  const yOf = (uv: number, k: number): number => {
    const t = (Math.log10(Math.max(LO_UV, Math.min(HI_UV, uv))) - Math.log10(LO_UV)) / (Math.log10(HI_UV) - Math.log10(LO_UV));
    return PAD_T + (h - PAD_T - PAD_B) * (1 - t * k);
  };
  const xOf = (ago: number): number => PAD_L + (w - PAD_L - PAD_R) * (1 - ago / WINDOW_S);
  const ticks = [
    { uv: 10, text: '10 µV' },
    { uv: 100, text: '100 µV' },
    { uv: 1000, text: '1 mV' },
    { uv: 10000, text: '10 mV' },
    { uv: 100000, text: '100 mV' },
  ];

  function fmt(uv: number): string {
    return uv >= 1000 ? `${(uv / 1000).toFixed(uv >= 10000 ? 0 : 1)} mV` : `${uv.toFixed(0)} µV`;
  }

  function collect(): void {
    const id = app.hello?.streams.find((s) => s.name === 'adc_raw')?.id ?? null;
    const ring = id === null ? undefined : app.rings.get(id);
    if (id === null || !ring || !ring.hasData) return;
    const fs = streamFs(id);
    const n = Math.max(4, Math.round(BUCKET_S * fs));
    const ch = app.config?.streams.find((s) => s.id === id)?.channels ?? [];
    const last = Math.floor(ring.head / n);
    const count = Math.ceil(WINDOW_S / BUCKET_S);
    const out: { ago: number; uv: number | null }[] = [];
    for (let k = last - count; k < last; k++) {
      const a = k * n;
      const ago = (ring.head - (a + n / 2)) / fs;
      if (a < ring.lo) continue;
      let sum = 0;
      let bad = false;
      for (let c = 0; c < Math.min(2, ring.nCh) && !bad; c++) {
        const d = ring.data[c];
        const scale = ch[c]?.scale ?? 0;
        let m = 0;
        for (let i = 0; i < n; i++) m += d[(a + i) % ring.cap];
        m /= n;
        if (m !== m) bad = true;
        let e = 0;
        for (let i = 0; i < n; i++) {
          const v = d[(a + i) % ring.cap] - m;
          e += v * v;
        }
        sum += Math.sqrt(e / n) * scale * 1e6;
      }
      out.push({ ago, uv: bad ? null : sum / Math.min(2, ring.nCh) });
    }
    values = out;
  }

  function build(): void {
    const k = grow.current;
    const parts: Pt[][] = [];
    let cur: Pt[] = [];
    for (const v of values) {
      if (v.uv === null) {
        if (cur.length > 1) parts.push(cur);
        cur = [];
      } else cur.push([xOf(v.ago), yOf(v.uv, k)]);
    }
    if (cur.length > 1) parts.push(cur);
    const base = h - PAD_B;
    runs = parts.map((p) => {
      const line = smoothPath(p);
      return { line, area: `${line}L${p[p.length - 1][0].toFixed(1)} ${base}L${p[0][0].toFixed(1)} ${base}Z` };
    });
    const lv = values[values.length - 1];
    end = lv && lv.uv !== null ? { x: xOf(lv.ago), y: yOf(lv.uv, k), uv: lv.uv } : null;
    if (!ready && values.length > 10) {
      ready = true;
      void grow.set(1);
    }
  }

  function move(e: PointerEvent): void {
    const r = box.getBoundingClientRect();
    const ago = (1 - (e.clientX - r.left - PAD_L) / (w - PAD_L - PAD_R)) * WINDOW_S;
    let best: { ago: number; uv: number | null } | null = null;
    for (const v of values) if (v.uv !== null && (!best || Math.abs(v.ago - ago) < Math.abs(best.ago - ago))) best = v;
    hover = best && best.uv !== null && Math.abs(best.ago - ago) < 0.5 ? { x: xOf(best.ago), y: yOf(best.uv, grow.current), uv: best.uv, ago: best.ago } : null;
  }

  onMount(() => {
    const ro = new ResizeObserver(() => {
      w = Math.max(200, box.clientWidth);
      h = Math.max(80, box.clientHeight);
    });
    ro.observe(box);
    let raf = 0;
    let lastT = 0;
    const loop = (t: number): void => {
      if (t - lastT > 33) {
        lastT = t;
        collect();
        build();
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  });
</script>

<div class="line" bind:this={box} onpointermove={move} onpointerleave={() => (hover = null)} role="img" aria-label="Vibration strength over the last 12 seconds">
  <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
    <defs>
      <linearGradient id="tone" gradientUnits="userSpaceOnUse" x1="0" x2="0" y1={h - PAD_B} y2={PAD_T}>
        <stop offset="0" stop-color="var(--tone-0)" />
        <stop offset="0.45" stop-color="var(--tone-1)" />
        <stop offset="1" stop-color="var(--tone-2)" />
      </linearGradient>
    </defs>
    {#each ticks as t (t.uv)}
      <line x1={PAD_L} x2={w - PAD_R} y1={yOf(t.uv, 1)} y2={yOf(t.uv, 1)} stroke="var(--grid)" />
      <text x={PAD_L - 8} y={yOf(t.uv, 1)} text-anchor="end" dominant-baseline="middle">{t.text}</text>
    {/each}
    <text x={PAD_L} y={h - 4}>12 s ago</text>
    <text x={w - PAD_R} y={h - 4} text-anchor="end">now</text>
    {#each runs as r, i (i)}
      <path d={r.area} fill="url(#tone)" opacity="0.1" />
      <path d={r.line} fill="none" stroke="url(#tone)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />
    {/each}
    {#if end}
      <circle cx={end.x} cy={end.y} r="5" fill="url(#tone)" stroke="var(--panel)" stroke-width="2" />
    {/if}
    {#if hover}
      <line x1={hover.x} x2={hover.x} y1={PAD_T} y2={h - PAD_B} stroke="var(--line2)" />
      <circle cx={hover.x} cy={hover.y} r="4" fill="var(--text)" stroke="var(--panel)" stroke-width="2" />
    {/if}
  </svg>
  {#if !ready}<div class="skel" aria-hidden="true"></div>{/if}
  {#if hover}
    <div class="tip" style:left={`${Math.min(hover.x + 10, w - 130)}px`} style:top={`${Math.max(2, hover.y - 34)}px`}>
      {fmt(hover.uv)} · {hover.ago.toFixed(1)} s ago
    </div>
  {/if}
</div>

<style>
  .line {
    position: relative;
    width: 100%;
    height: 100%;
    min-height: 90px;
    overflow: hidden;
  }
  svg {
    position: absolute;
    inset: 0;
    display: block;
  }
  text {
    fill: var(--muted);
    font-size: 10.5px;
  }
  .skel {
    position: absolute;
    inset: 10px 16px 18px 48px;
    border-radius: 8px;
  }
</style>
