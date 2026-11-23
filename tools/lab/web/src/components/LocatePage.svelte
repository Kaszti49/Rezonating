<script lang="ts">
  // Locate: where did a step come from? Top view of the device with 1 m rings; each step is a wedge at its bearing,
  // with a dashed mirror wedge (two geophones can't tell front from back). WEB_API.md section 15.
  import { onMount } from 'svelte';
  import { app } from '../lib/store.svelte';
  import { bandRange, locateApi, type LocateStep } from '../lib/locate';

  const FADE_MS = 9000;
  const DEVICE_R_M = 0.093; // OTIO case v1: diameter 186.4 mm
  // Ripples: like a drop hitting water, rings spread from where the step landed (a picture, not the real wave speed).
  const RIPPLE_MS = 2600;
  const RIPPLE_RINGS = 3;
  const RIPPLE_MAX_M = 0.9;

  let canvas: HTMLCanvasElement;
  let box: HTMLDivElement;
  let maxM = $state(3);
  let showMirror = $state(true);
  let showRipples = $state(true);
  let speedText = $state('');

  /** When each step arrived in this page (performance.now()), for the fade. */
  const seenAt = new Map<number, number>();

  const st = $derived(app.locate);
  const cal = $derived(st?.calibration ?? null);
  const steps = $derived(app.locateSteps);
  const last = $derived(steps.length ? steps[steps.length - 1] : null);
  const connected = $derived(app.connection?.state === 'connected');
  const antiPhase = $derived.by(() => {
    const recent = steps.slice(-20).filter((s) => Math.abs(s.cc) >= 0.3);
    if (!recent.length) return null;
    return recent.filter((s) => s.cc < 0).length / recent.length;
  });

  onMount(() => {
    const now = performance.now();
    void locateApi
      .view()
      .then((v) => {
        app.locate = { ...v, recent: undefined };
        if (!app.locateSteps.length && v.recent) {
          for (const s of v.recent) seenAt.set(s.id, now - FADE_MS * 0.6); // older steps: shown half faded
          app.locateSteps = v.recent;
        }
      })
      .catch(() => {});
    let raf = 0;
    const loop = () => {
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
    const cx = w / 2;
    const cy = h / 2;
    const s = (Math.min(w, h) / 2 - 28) / maxM; // px per metre
    const text = css('--text');
    const muted = css('--muted');
    const grid = css('--grid');
    const accent = css('--accent');
    const left = css('--ch0');
    const right = css('--ch1');

    // floor: rings every metre, cross, labels
    g.lineWidth = 1;
    g.strokeStyle = grid;
    g.fillStyle = muted;
    g.font = '12px system-ui, sans-serif';
    g.textAlign = 'left';
    for (let r = 1; r <= maxM; r++) {
      g.beginPath();
      g.arc(cx, cy, r * s, 0, Math.PI * 2);
      g.stroke();
      g.fillText(`${r} m`, cx + 4, cy - r * s + 14);
    }
    g.beginPath();
    g.moveTo(cx - maxM * s, cy);
    g.lineTo(cx + maxM * s, cy);
    g.moveTo(cx, cy - maxM * s);
    g.lineTo(cx, cy + maxM * s);
    g.stroke();
    g.font = '600 13px system-ui, sans-serif';
    g.textAlign = 'center';
    g.fillStyle = left;
    g.fillText('LEFT', cx - maxM * s + 22, cy - 8);
    g.fillStyle = right;
    g.fillText('RIGHT', cx + maxM * s - 24, cy - 8);
    g.fillStyle = muted;
    g.fillText('FRONT', cx, cy - maxM * s - 8);
    g.fillText('BACK (mirror of front)', cx, cy + maxM * s + 18);

    // steps, oldest first
    const now = performance.now();
    for (const st of steps) {
      if (!seenAt.has(st.id)) seenAt.set(st.id, now);
      const age = now - (seenAt.get(st.id) ?? now);
      const alpha = Math.max(0, 1 - age / FADE_MS);
      if (alpha <= 0.02) continue;
      const isLast = st === last;
      const col = st.side === 'left' ? left : st.side === 'right' ? right : muted;
      drawStep(g, st, cx, cy, s, col, alpha * (isLast ? 1 : 0.55), isLast);
      if (showRipples && age < RIPPLE_MS) drawRipples(g, st, cx, cy, s, col, age);
    }
    for (const id of seenAt.keys()) if (!steps.some((x) => x.id === id)) seenAt.delete(id);

    // the device: case outline (at least 16 px) with its two geophones
    const dr = Math.max(16, DEVICE_R_M * s);
    g.beginPath();
    g.arc(cx, cy, dr, 0, Math.PI * 2);
    g.fillStyle = css('--panel2');
    g.fill();
    g.lineWidth = 2;
    g.strokeStyle = accent;
    g.stroke();
    const gx = dr * 0.62;
    const swap = cal?.swap_sides ?? false;
    for (const [x, ch] of [
      [-gx, swap ? 1 : 0],
      [gx, swap ? 0 : 1],
    ] as const) {
      g.beginPath();
      g.arc(cx + x, cy, Math.max(3, dr * 0.22), 0, Math.PI * 2);
      g.fillStyle = x < 0 ? left : right;
      g.fill();
      g.fillStyle = text;
      g.font = '10px system-ui, sans-serif';
      g.fillText(`ch${ch}`, cx + x, cy + dr + 12);
    }
  }

  function wedge(
    g: CanvasRenderingContext2D,
    cx: number,
    cy: number,
    s: number,
    phiDeg: number,
    sigmaDeg: number,
    r0: number,
    r1: number,
  ): void {
    // bearing from +y (screen up) towards +x (screen right): canvas angle = phi - 90 deg
    const a0 = ((phiDeg - sigmaDeg - 90) * Math.PI) / 180;
    const a1 = ((phiDeg + sigmaDeg - 90) * Math.PI) / 180;
    g.beginPath();
    g.arc(cx, cy, r1 * s, a0, a1);
    g.arc(cx, cy, r0 * s, a1, a0, true);
    g.closePath();
  }

  function drawStep(
    g: CanvasRenderingContext2D,
    st: LocateStep,
    cx: number,
    cy: number,
    s: number,
    col: string,
    alpha: number,
    strong: boolean,
  ): void {
    const [r0, r1] = bandRange(st, maxM);
    g.save();
    g.globalAlpha = alpha;
    if (st.phi_deg === null) {
      // no bearing: only the side, as a faint half-disc
      if (st.side === 'unsure') {
        g.restore();
        return;
      }
      const phi = st.side === 'left' ? -90 : 90;
      wedge(g, cx, cy, s, phi, 90, r0, r1);
      g.globalAlpha = alpha * 0.18;
      g.fillStyle = col;
      g.fill();
      g.restore();
      return;
    }
    const known = st.distance_m !== null;
    wedge(g, cx, cy, s, st.phi_deg, st.phi_sigma_deg, r0, r1);
    g.globalAlpha = alpha * (known ? 0.45 : 0.22);
    g.fillStyle = col;
    g.fill();
    g.globalAlpha = alpha;
    g.lineWidth = strong ? 2 : 1;
    g.strokeStyle = col;
    g.stroke();
    if (showMirror) {
      wedge(g, cx, cy, s, 180 - st.phi_deg, st.phi_sigma_deg, r0, r1);
      g.globalAlpha = alpha * 0.08;
      g.fill();
      g.globalAlpha = alpha * 0.7;
      g.setLineDash([5, 5]);
      g.lineWidth = 1;
      g.stroke();
      g.setLineDash([]);
    }
    if (strong && known && st.distance_m !== null) {
      const rad = ((st.phi_deg - 90) * Math.PI) / 180;
      const r = Math.min(st.distance_m, maxM);
      g.globalAlpha = alpha;
      g.beginPath();
      g.arc(cx + Math.cos(rad) * r * s, cy + Math.sin(rad) * r * s, 6, 0, Math.PI * 2);
      g.fillStyle = col;
      g.fill();
    }
    g.restore();
  }

  /** Where the ripple starts: the bearing (or straight left/right with only a side) at the estimated distance,
   * or the middle of the drawn band when the distance is not calibrated. Null: nothing to show. */
  function rippleCentre(st: LocateStep): { phi: number; r: number } | null {
    const phi = st.phi_deg ?? (st.side === 'left' ? -90 : st.side === 'right' ? 90 : null);
    if (phi === null) return null;
    const [r0, r1] = bandRange(st, maxM);
    const r = st.distance_m !== null ? Math.min(st.distance_m, maxM) : Math.min(1.5, (r0 + r1) / 2);
    return { phi, r };
  }

  function drawRipples(
    g: CanvasRenderingContext2D,
    st: LocateStep,
    cx: number,
    cy: number,
    s: number,
    col: string,
    ageMs: number,
  ): void {
    const c = rippleCentre(st);
    if (!c) return;
    const centres: { phi: number; mirror: boolean }[] = [{ phi: c.phi, mirror: false }];
    if (showMirror && st.phi_deg !== null) centres.push({ phi: 180 - c.phi, mirror: true });
    const t = ageMs / RIPPLE_MS;
    g.save();
    g.strokeStyle = col;
    for (const { phi, mirror } of centres) {
      const rad = ((phi - 90) * Math.PI) / 180;
      const x = cx + Math.cos(rad) * c.r * s;
      const y = cy + Math.sin(rad) * c.r * s;
      // the impact: a bright drop that fades fast
      if (t < 0.25) {
        g.globalAlpha = (1 - t / 0.25) * (mirror ? 0.35 : 0.9);
        g.beginPath();
        g.arc(x, y, 5, 0, Math.PI * 2);
        g.fillStyle = col;
        g.fill();
      }
      // rings leave one after another, grow and fade
      for (let k = 0; k < RIPPLE_RINGS; k++) {
        const tk = t - k * 0.18;
        if (tk <= 0 || tk >= 1) continue;
        const ease = 1 - (1 - tk) * (1 - tk); // fast at first, then slowing, like water
        g.globalAlpha = (1 - tk) * (mirror ? 0.3 : 0.85);
        g.lineWidth = (mirror ? 1 : 2) * (1 - tk) + 0.5;
        g.setLineDash(mirror ? [4, 4] : []);
        g.beginPath();
        g.arc(x, y, Math.max(1, ease * RIPPLE_MAX_M * s), 0, Math.PI * 2);
        g.stroke();
      }
    }
    g.restore();
  }

  function sideWord(sd: string | undefined): string {
    return sd === 'left' ? 'LEFT' : sd === 'right' ? 'RIGHT' : sd === 'unsure' ? '?' : '–';
  }
  /** "35° left of front": the bearing in words, measured from straight ahead (or straight behind, its mirror). */
  function bearingText(phi: number, from: 'front' | 'back'): string {
    const a = Math.round(Math.abs(phi));
    if (a === 0) return `straight ${from === 'front' ? 'ahead' : 'behind'}`;
    if (a === 90) return `straight ${phi < 0 ? 'left' : 'right'}`;
    return `${a}° ${phi < 0 ? 'left' : 'right'} of ${from}`;
  }
  const bandText: Record<string, string> = {
    near: 'near (< 1 m)',
    mid: '1–2 m',
    far: 'far (> 2 m)',
    unknown: 'not calibrated',
  };

  async function calibrate(spot: 'left' | 'right'): Promise<void> {
    await app.run('locate', async () => (app.locate = await locateApi.calibrate(spot)));
  }
  async function cancelCal(): Promise<void> {
    await app.run('locate', async () => (app.locate = await locateApi.cancel()));
  }
  async function resetCal(): Promise<void> {
    if (!confirm('Forget the calibration (wave speed, timing offset, gain, distance)?')) return;
    await app.run('locate', async () => (app.locate = await locateApi.reset()));
  }
  async function clearTrail(): Promise<void> {
    await app.run('locate', async () => (app.locate = await locateApi.clear()));
    app.locateSteps = [];
  }
  async function setSpeed(): Promise<void> {
    const v = Number(speedText);
    if (!Number.isFinite(v) || v < 10 || v > 2000) {
      app.toast('Wave speed: 10 to 2000 m/s.', 'error');
      return;
    }
    await app.run('locate', async () => (app.locate = await locateApi.settings({ c_mps: v })));
    speedText = '';
  }
</script>

<section class="locate">
  <div class="radar" bind:this={box}>
    <canvas bind:this={canvas} aria-label="Top view of the device and the located steps"></canvas>
    {#if !connected}
      <div class="overlay">
        <p>No node connected.</p>
        <p class="muted">Connect on the Device page: the S3 rig on its USB port, or the Simulator (a person walking around the device).</p>
      </div>
    {/if}
  </div>

  <aside class="side">
    <div class="card big">
      <div class="sideword" class:l={last?.side === 'left'} class:r={last?.side === 'right'}>{sideWord(last?.side)}</div>
      {#if last}
        <dl>
          <dt>Bearing</dt>
          <dd>
            {#if last.phi_deg !== null}
              {bearingText(last.phi_deg, 'front')} ± {Math.round(last.phi_sigma_deg)}°
              <span class="muted">or {bearingText(last.phi_deg, 'back')}</span>
            {:else}
              –
            {/if}
          </dd>
          <dt>Distance</dt>
          <dd>{last.distance_m !== null ? `~${last.distance_m.toFixed(1)} m, ` : ''}{bandText[last.distance_band]}</dd>
          <dt>Time gap</dt>
          <dd>
            {Math.round(last.tau_s * 1e6)} µs{#if st?.fs_hz}&nbsp;({(last.tau_s * st.fs_hz).toFixed(2)} samples){/if}
          </dd>
          <dt>Votes</dt>
          <dd>timing {last.side_votes.timing}, loudness {last.side_votes.amplitude}</dd>
          <dt>Confidence</dt>
          <dd>{Math.round(last.confidence * 100)} %{#if last.lag_limited}&nbsp;<span class="warn">(timing off the scale)</span>{/if}</dd>
        </dl>
      {:else}
        <p class="muted">Waiting for a step…</p>
      {/if}
    </div>

    <div class="card">
      <header><h2>Calibration</h2></header>
      {#if cal}
        <p class="small">
          Wave speed <b>{Math.round(cal.c_mps)} m/s</b>{cal.calibrated.length ? '' : ' (a guess)'} · gain ch1/ch0 {cal.gain_ratio.toFixed(2)}
          · distance {cal.ref_amp !== null ? 'calibrated' : 'not calibrated'}{cal.swap_sides ? ' · sides swapped' : ''}
        </p>
        <p class="small muted">Done: {cal.calibrated.length ? cal.calibrated.join(', ') : 'nothing yet'}</p>
      {/if}
      {#if st?.calibrating}
        <p class="calnow">
          Step {st.calibrating.want} times at <b>1 m straight {st.calibrating.spot}</b> of the device: {st.calibrating.got} / {st.calibrating.want}
        </p>
        <button onclick={cancelCal}>Cancel</button>
      {:else}
        <div class="row">
          <button class="primary" onclick={() => calibrate('left')} disabled={!connected}>Calibrate: 1 m left</button>
          <button class="primary" onclick={() => calibrate('right')} disabled={!connected}>Calibrate: 1 m right</button>
        </div>
        <p class="small muted">Do both: left then right. Stand still between steps, one foot at the spot.</p>
      {/if}
      {#each st?.notes ?? [] as n (n)}
        <p class="small note">{n}</p>
      {/each}
      <div class="row">
        <input type="number" placeholder="m/s" min="10" max="2000" bind:value={speedText} style="width:80px" aria-label="Wave speed in m/s" />
        <button onclick={setSpeed}>Set wave speed</button>
        <button class="danger" onclick={resetCal}>Reset</button>
      </div>
    </div>

    <div class="card">
      <header><h2>View</h2></header>
      <div class="row">
        <span class="seg">
          {#each [2, 3, 5] as m (m)}
            <button class:on={maxM === m} onclick={() => (maxM = m)}>{m} m</button>
          {/each}
        </span>
        <label><input type="checkbox" bind:checked={showMirror} /> mirror</label>
        <label><input type="checkbox" bind:checked={showRipples} /> ripples</label>
        <button onclick={clearTrail}>Clear trail</button>
      </div>
      <p class="small muted">
        Solid wedge: the bearing, drawn in front. Dashed: the same bearing behind. With two geophones on one line,
        front and back look identical. Ripples spread from where each step landed, like a drop on water; before the
        distance is calibrated, they start at a guessed 1.5 m.
      </p>
    </div>

    <div class="card">
      <header><h2>Counts</h2></header>
      <p class="small">
        Steps {st?.steps ?? 0} · skipped (lost samples) {st?.skipped_gaps ?? 0}
        {#if antiPhase !== null}· anti-phase {Math.round(antiPhase * 100)} % of the last steps{/if}
      </p>
      {#if antiPhase !== null && antiPhase > 0.7}
        <p class="small note">
          The channels move in opposite directions: a reversed geophone or the case rocking. Drop a coin on the
          middle of the lid: same sign on both traces means rocking.
        </p>
      {/if}
    </div>
  </aside>
</section>

<style>
  .locate {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 340px;
    gap: 12px;
    height: 100%;
    min-height: 520px;
  }
  .radar {
    position: relative;
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 8px;
    min-height: 480px;
    overflow: hidden;
  }
  canvas {
    position: absolute;
    inset: 0;
  }
  .overlay {
    position: absolute;
    inset: auto 0 16px 0;
    text-align: center;
  }
  .overlay p {
    margin: 2px;
  }
  .side {
    display: flex;
    flex-direction: column;
    gap: 10px;
    overflow: auto;
  }
  .big {
    text-align: left;
  }
  .sideword {
    font-size: 54px;
    font-weight: 800;
    letter-spacing: 2px;
    text-align: center;
    color: var(--muted);
    line-height: 1.1;
    margin: 4px 0 8px;
  }
  .sideword.l {
    color: var(--ch0);
  }
  .sideword.r {
    color: var(--ch1);
  }
  dl {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 3px 10px;
    margin: 0;
    font-size: 13px;
  }
  dt {
    color: var(--muted);
  }
  dd {
    margin: 0;
  }
  h2 {
    font-size: 14px;
    margin: 0;
  }
  .small {
    font-size: 12.5px;
    margin: 4px 0;
  }
  .muted {
    color: var(--muted);
  }
  .warn,
  .note {
    color: var(--warn);
  }
  .calnow {
    font-size: 14px;
    margin: 6px 0;
  }
  .row {
    margin-top: 6px;
  }
  @media (max-width: 900px) {
    .locate {
      grid-template-columns: 1fr;
    }
  }
</style>
