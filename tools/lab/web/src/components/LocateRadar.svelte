<script lang="ts">
  // The Locate radar: the device in the middle, a left and a right area, and front/back/far. It shows a side, not a
  // position: the rings and the sweep are a picture. Used by the Home page and the Locate page.
  import { onMount } from 'svelte';
  import { app } from '../lib/store.svelte';
  import { locateApi, type LocateStep, type Side } from '../lib/locate';
  import { reducedMotion } from '../lib/home';

  interface Props {
    ripples?: boolean;
    labels?: boolean;
  }
  let { ripples = true, labels = true }: Props = $props();

  const RIPPLE_MS = 2400;
  const RINGS = 3;
  const FADE_MS = 4500;
  const SWEEP_MS = 5200;

  let canvas: HTMLCanvasElement;
  let box: HTMLDivElement;
  /** When each step arrived in this page (performance.now()). */
  const seenAt = new Map<number, number>();
  const still = reducedMotion();

  onMount(() => {
    const now = performance.now();
    void locateApi
      .view()
      .then((v) => {
        app.locate = { ...v, recent: undefined };
        if (!app.locateSteps.length && v.recent) {
          for (const s of v.recent) seenAt.set(s.id, now - FADE_MS); // older steps are not shown as new
          app.locateSteps = v.recent;
        }
      })
      .catch(() => {});
    let raf = 0;
    const loop = (): void => {
      draw();
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  });

  function css(name: string): string {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888';
  }

  function draw(): void {
    if (!canvas || !box) return;
    const dpr = window.devicePixelRatio || 1;
    const w = box.clientWidth;
    const h = box.clientHeight;
    if (w < 10 || h < 10) return;
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
    const now = performance.now();
    const cx = w / 2;
    const cy = h / 2;
    const R = Math.min(w, h) / 2 - (labels ? 26 : 8);
    const left = css('--side-left');
    const right = css('--side-right');
    const none = css('--side-none');
    const muted = css('--muted');
    const colour = (s: Side): string => (s === 'left' ? left : s === 'right' ? right : none);

    // rings
    g.strokeStyle = css('--line2');
    g.lineWidth = 1;
    for (const k of [1 / 3, 2 / 3, 1]) {
      g.beginPath();
      g.arc(cx, cy, R * k, 0, Math.PI * 2);
      g.stroke();
    }

    // sweep
    if (!still) {
      const a = ((now % SWEEP_MS) / SWEEP_MS) * Math.PI * 2;
      const accent = css('--side-left');
      for (let i = 0; i < 26; i++) {
        g.globalAlpha = 0.13 * (1 - i / 26);
        g.fillStyle = accent;
        g.beginPath();
        g.moveTo(cx, cy);
        g.arc(cx, cy, R, a - (i + 1) * 0.028, a - i * 0.028);
        g.closePath();
        g.fill();
      }
      g.globalAlpha = 1;
    }

    // the last step lights up its area: left and right are 120 degrees wide, front and back 60
    const steps = app.locateSteps;
    for (const s of steps) if (!seenAt.has(s.id)) seenAt.set(s.id, now);
    const last = steps.length ? steps[steps.length - 1] : null;
    if (last) {
      const age = now - (seenAt.get(last.id) ?? 0);
      const al = Math.max(0, 1 - age / FADE_MS);
      if (al > 0) for (const [a0, a1] of sectors(last.side)) sector(g, cx, cy, R, a0, a1, colour(last.side), 0.5 * al);
    }

    if (ripples && !still) {
      for (const s of steps) {
        const age = now - (seenAt.get(s.id) ?? now);
        if (age < RIPPLE_MS) ripple(g, s, cx, cy, R, colour(s.side), age);
      }
    }
    for (const id of seenAt.keys()) if (!steps.some((x) => x.id === id)) seenAt.delete(id);

    // the device with its two geophones
    const dr = Math.max(15, R * 0.12);
    g.beginPath();
    g.arc(cx, cy, dr, 0, Math.PI * 2);
    g.fillStyle = css('--panel2');
    g.fill();
    g.lineWidth = 1.5;
    g.strokeStyle = css('--line2');
    g.stroke();
    for (const [x, col] of [
      [-dr * 0.48, left],
      [dr * 0.48, right],
    ] as const) {
      g.beginPath();
      g.arc(cx + x, cy, dr * 0.2, 0, Math.PI * 2);
      g.fillStyle = col;
      g.fill();
    }

    if (labels) {
      g.font = '600 11px system-ui, sans-serif';
      g.fillStyle = muted;
      g.textAlign = 'center';
      g.textBaseline = 'middle';
      g.fillText('FRONT', cx, cy - R - 13);
      g.fillText('BACK', cx, cy + R + 13);
      g.textAlign = 'right';
      g.fillText('LEFT', cx - R - 8, cy);
      g.textAlign = 'left';
      g.fillText('RIGHT', cx + R + 8, cy);
    }
  }

  function sectors(side: Side): [number, number][] {
    const d = Math.PI / 180;
    if (side === 'left') return [[120 * d, 240 * d]];
    if (side === 'right') return [[-60 * d, 60 * d]];
    return [
      [-120 * d, -60 * d],
      [60 * d, 120 * d],
    ];
  }

  function sector(
    g: CanvasRenderingContext2D,
    cx: number,
    cy: number,
    R: number,
    a0: number,
    a1: number,
    col: string,
    alpha: number,
  ): void {
    const grd = g.createRadialGradient(cx, cy, R * 0.1, cx, cy, R);
    const clear = /^#[0-9a-f]{6}$/i.test(col) ? `${col}00` : 'transparent'; // the same hue, so no grey fringe
    grd.addColorStop(0, clear);
    grd.addColorStop(0.5, col);
    grd.addColorStop(1, clear);
    g.globalAlpha = alpha;
    g.fillStyle = grd;
    g.beginPath();
    g.moveTo(cx, cy);
    g.arc(cx, cy, R, a0, a1);
    g.closePath();
    g.fill();
    g.globalAlpha = 1;
  }

  function ripple(
    g: CanvasRenderingContext2D,
    s: LocateStep,
    cx: number,
    cy: number,
    R: number,
    col: string,
    ageMs: number,
  ): void {
    const t = ageMs / RIPPLE_MS;
    const at: [number, number][] =
      s.side === 'left'
        ? [[cx - R * 0.6, cy]]
        : s.side === 'right'
          ? [[cx + R * 0.6, cy]]
          : [
              [cx, cy - R * 0.6],
              [cx, cy + R * 0.6],
            ];
    g.save();
    g.strokeStyle = col;
    for (const [x, y] of at) {
      if (t < 0.3) {
        g.globalAlpha = (1 - t / 0.3) * 0.95;
        g.beginPath();
        g.arc(x, y, 5, 0, Math.PI * 2);
        g.fillStyle = col;
        g.fill();
      }
      for (let k = 0; k < RINGS; k++) {
        const tk = t - k * 0.16;
        if (tk <= 0 || tk >= 1) continue;
        const ease = 1 - (1 - tk) * (1 - tk);
        g.globalAlpha = (1 - tk) * 0.8;
        g.lineWidth = 2 * (1 - tk) + 0.5;
        g.beginPath();
        g.arc(x, y, Math.max(1, ease * R * 0.38), 0, Math.PI * 2);
        g.stroke();
      }
    }
    g.restore();
  }
</script>

<div class="radar" bind:this={box}>
  <canvas bind:this={canvas} aria-label="Radar: the side the last step came from"></canvas>
</div>

<style>
  .radar {
    position: relative;
    width: 100%;
    height: 100%;
    min-height: 160px;
  }
  canvas {
    position: absolute;
    inset: 0;
  }
</style>
