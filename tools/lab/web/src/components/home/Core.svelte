<script lang="ts">
  // The living ring: the connect button while nothing is connected, the health ring afterwards. Its shape moves with the
  // real vibration once data flows (two closed SVG paths whose points are interpolated every frame).
  import { onMount } from 'svelte';
  import { Tween } from 'svelte/motion';
  import { cubicOut } from 'svelte/easing';
  import { app } from '../../lib/store.svelte';
  import { reducedMotion, ringPath } from '../../lib/home';

  interface Props {
    mood: 'idle' | 'busy' | 'live';
    /** Share of the health checks that pass, 0..1 (live only). */
    health?: number;
    warn?: boolean;
  }
  let { mood, health = 0, warn = false }: Props = $props();

  const N = 72;
  const R = 74;
  const ARC = 2 * Math.PI * 88;
  const r1 = new Float32Array(N);
  const r2 = new Float32Array(N);
  let d1 = $state('');
  let d2 = $state('');
  const still = reducedMotion();
  const amp = new Tween(2.5, { duration: still ? 0 : 700, easing: cubicOut });
  const arc = new Tween(0, { duration: still ? 0 : 1100, easing: cubicOut });

  $effect(() => {
    void amp.set(mood === 'busy' ? 8 : mood === 'idle' ? 3 : 1.6);
  });
  $effect(() => {
    void arc.set(mood === 'live' ? health : 0);
  });

  /** Loudness of the last 100 ms over the floor's quiet level, 0..1 (about 40 dB). */
  function level(): number {
    const id = app.hello?.streams.find((s) => s.name === 'adc_raw')?.id;
    const ring = id === undefined ? undefined : app.rings.get(id);
    const quiet = app.locate?.health?.quiet ?? null;
    if (!ring || !ring.hasData || quiet === null || quiet <= 0) return 0;
    const n = 200;
    let s = 0;
    let m = 0;
    const d = ring.data[0];
    for (let i = 1; i <= n; i++) m += d[(ring.head - i + ring.cap) % ring.cap];
    m /= n;
    for (let i = 1; i <= n; i++) {
      const v = d[(ring.head - i + ring.cap) % ring.cap] - m;
      s += v * v;
    }
    const rms = Math.sqrt(s / n);
    if (!(rms > 0)) return 0;
    return Math.max(0, Math.min(1, (20 * Math.log10(rms / quiet) - 6) / 40));
  }

  onMount(() => {
    let raf = 0;
    let lv = 0;
    const loop = (t: number): void => {
      const target = mood === 'live' ? level() : 0;
      lv += (target - lv) * (target > lv ? 0.35 : 0.06); // up fast, down slowly, like a floor ringing out
      const a = amp.current + lv * 15;
      const s = t / 1000;
      const speed = mood === 'busy' ? 2.6 : 1;
      for (let i = 0; i < N; i++) {
        const p = (i / N) * Math.PI * 2;
        r1[i] = R + a * (0.55 * Math.sin(3 * p + s * 0.9 * speed) + 0.45 * Math.sin(5 * p - s * 1.3 * speed));
        r2[i] = R + a * (0.6 * Math.sin(4 * p - s * 0.7 * speed + 1) + 0.4 * Math.sin(7 * p + s * 1.1 * speed));
      }
      d1 = ringPath(r1);
      d2 = ringPath(r2);
      if (!still) raf = requestAnimationFrame(loop);
    };
    loop(performance.now());
    return () => cancelAnimationFrame(raf);
  });
</script>

<svg class="core {mood}" viewBox="-100 -100 200 200" aria-hidden="true">
  <defs>
    <radialGradient id="coreFill">
      <stop offset="0" stop-color="var(--side-left)" stop-opacity="0.2" />
      <stop offset="0.75" stop-color="var(--side-left)" stop-opacity="0.07" />
      <stop offset="1" stop-color="var(--side-left)" stop-opacity="0" />
    </radialGradient>
  </defs>
  <circle r="96" fill="url(#coreFill)" />
  <path d={d2} fill="none" stroke="var(--side-left)" stroke-opacity="0.35" stroke-width="1.5" />
  <path d={d1} fill="none" stroke="var(--side-left)" stroke-width="2.4" />
  {#if mood === 'live'}
    <circle r="88" fill="none" stroke="var(--line)" stroke-width="4" />
    <circle
      class="arc"
      r="88"
      fill="none"
      stroke={warn ? 'var(--warn)' : 'var(--ok)'}
      stroke-width="4"
      stroke-linecap="round"
      stroke-dasharray={`${Math.max(0.01, arc.current) * ARC} ${ARC}`}
      transform="rotate(-90)"
    />
  {/if}
</svg>

<style>
  .core {
    width: 100%;
    height: 100%;
    display: block;
    overflow: visible;
  }
</style>
