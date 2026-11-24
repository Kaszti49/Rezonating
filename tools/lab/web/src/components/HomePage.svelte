<script lang="ts">
  // Home: one connect button that becomes the dashboard. Nothing is typed in here: the health comes from the node and the
  // server, the results from the experiment notes. Simulated data always says SIMULATION.
  import { onMount, tick } from 'svelte';
  import { api, type ConnectRequest } from '../lib/api';
  import { app } from '../lib/store.svelte';
  import type { PortInfo } from '../lib/types';
  import { locateApi, SIDE_WORD, REASON_TEXT } from '../lib/locate';
  import { deviceChecks, reducedMotion } from '../lib/home';
  import Core from './home/Core.svelte';
  import Counter from './home/Counter.svelte';
  import HeatMap from './home/HeatMap.svelte';
  import ResultsTile from './home/ResultsTile.svelte';
  import VibrationLine from './home/VibrationLine.svelte';
  import LocateRadar from './LocateRadar.svelte';

  interface Props {
    onGo: (path: string) => void;
    groups: { name: string; pages: { path: string; label: string }[] }[];
  }
  let { onGo, groups }: Props = $props();

  type Phase = 'idle' | 'busy' | 'live';
  let phase = $state<Phase>('idle');
  let node = $state.raw<PortInfo | null>(null);
  let message = $state('');
  let menu = $state(false);

  const link = $derived(app.connection?.state ?? 'disconnected');
  const sim = $derived(app.connection?.embedded_sim === true || app.connection?.link === 'sim' || (app.hello?.node_id ?? '').includes('sim'));
  const checks = $derived(deviceChecks(app.status, app.locate));
  const passed = $derived(checks.filter((c) => c.state === 'ok').length);
  const warned = $derived(checks.filter((c) => c.state === 'warn').length);
  const raw = $derived(app.status?.streams.find((s) => s.name === 'adc_raw') ?? null);
  const rate = $derived(raw?.rate_hz_fit ?? raw?.rate_hz_status ?? 0);
  const steps = $derived(app.locateSteps);
  const last = $derived(steps.length ? steps[steps.length - 1] : null);
  const sides = $derived(app.locate?.sides ?? { left: 0, right: 0, same: 0 });
  const why = $derived(last ? REASON_TEXT[last.reason] + (last.walk_steps >= 2 ? `, this walk: ${SIDE_WORD[last.walk_side].toLowerCase()}` : '') : '');
  const total = $derived(sides.left + sides.right + sides.same);

  /** Change the layout as one morph: the ring moves from the middle into its tile (View Transitions; else at once). */
  function morph(to: Phase): void {
    if (phase === to) return;
    const apply = async (): Promise<void> => {
      phase = to;
      await tick();
    };
    if (!document.startViewTransition || reducedMotion()) {
      void apply();
      return;
    }
    const t = document.startViewTransition(apply);
    // a newer morph replaces this one: that is no error
    t.ready.catch(() => {});
    t.finished.catch(() => {});
  }

  // Follow the link: already connected when the page opens (a short look at the ring first), or lost while it is open.
  let opened = false;
  $effect(() => {
    const s = link;
    if (s === 'connected') {
      const wait = opened ? 250 : 900;
      opened = true;
      const t = window.setTimeout(() => morph('live'), wait);
      if (phase === 'idle') morph('busy');
      return () => window.clearTimeout(t);
    }
    if (s === 'connecting') morph('busy');
    else if (s === 'disconnected') morph('idle');
    return undefined;
  });

  async function lookForNode(): Promise<void> {
    if (link === 'connected' || link === 'connecting' || document.hidden) return;
    try {
      node = (await api.ports()).ports.find((p) => p.is_node) ?? null;
      if (node) message = '';
    } catch {
      node = null;
    }
  }

  async function go(req: ConnectRequest): Promise<void> {
    message = '';
    morph('busy');
    const err = await app.run('connect', () => api.connect({ ...req, start: true }), true);
    if (err) {
      message = err.message;
      morph('idle');
    }
  }

  async function connect(): Promise<void> {
    if (phase !== 'idle') return;
    await lookForNode();
    if (node) await go({ kind: 'serial', url: node.device });
    else message = 'No device found. Plug its USB cable in, or start the simulation.';
  }

  async function disconnect(): Promise<void> {
    menu = false;
    await app.disconnect();
  }

  async function saveReference(): Promise<void> {
    await app.run('locate', async () => (app.locate = await locateApi.saveBaseline()));
  }

  function leave(path: string): void {
    menu = false;
    onGo(path);
  }

  onMount(() => {
    void lookForNode();
    const t = window.setInterval(() => void lookForNode(), 2500);
    const esc = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') menu = false;
    };
    window.addEventListener('keydown', esc);
    return () => {
      window.clearInterval(t);
      window.removeEventListener('keydown', esc);
    };
  });
</script>

<section class="home {phase}">
  <header class="top">
    <span class="brand">REZON</span>
    {#if sim && phase === 'live'}<span class="badge">SIMULATION</span>{/if}
    <span class="grow"></span>
    {#if phase === 'live'}
      <button class="ghost" onclick={() => leave('/record')}>
        {#if app.recActive}<span class="dot err" aria-hidden="true"></span> Recording{:else}Start recording{/if}
      </button>
    {/if}
    <button class="ghost" onclick={() => (menu = !menu)} aria-expanded={menu} aria-haspopup="true">Lab</button>
    {#if menu}
      <div class="menu">
        {#each groups as grp (grp.name)}
          <div>
            <h3>{grp.name}</h3>
            {#each grp.pages as p (p.path)}<button onclick={() => leave(p.path)}>{p.label}</button>{/each}
          </div>
        {/each}
        <div class="menufoot">
          <button onclick={() => app.setTheme(app.theme === 'dark' ? 'light' : 'dark')}>Theme: {app.theme}</button>
          {#if link === 'connected'}<button onclick={disconnect}>Disconnect</button>{/if}
        </div>
      </div>
    {/if}
  </header>

  {#if phase !== 'live'}
    <div class="stage">
      <button class="orb" onclick={connect} disabled={phase === 'busy'} aria-label={phase === 'busy' ? 'Connecting' : 'Connect the device'}>
        <span class="coreBig"><Core mood={phase === 'busy' ? 'busy' : 'idle'} /></span>
        <span class="orbText">{phase === 'busy' ? 'Connecting' : 'Connect'}</span>
      </button>
      <p class="hint" role="status">
        {#if app.ws !== 'open'}
          The lab server is not running.
        {:else if message}
          {message}
        {:else if phase === 'busy'}
          Listening to the floor…
        {:else if node}
          <span class="dot ok" aria-hidden="true"></span> Device ready on {node.device}
        {:else}
          Looking for the device…
        {/if}
      </p>
      {#if phase === 'idle' && !node}
        <button class="ghost" onclick={() => go({ kind: 'sim' })}>Start the simulation</button>
      {/if}
    </div>
  {:else}
    <div class="bento">
      <article class="tile radar" style="--i:0">
        <h2>Where the step came from</h2>
        <div class="fill"><LocateRadar /></div>
        <div class="answer" class:l={last?.side === 'left'} class:r={last?.side === 'right'}>
          <b>{last ? SIDE_WORD[last.side] : 'Waiting for a step'}</b>
          <span class="muted">
            {last ? why : 'walk past the device'}
          </span>
        </div>
      </article>

      <article class="tile health" style="--i:1">
        <div class="ring">
          <span class="coreSmall"><Core mood="live" health={checks.length ? passed / checks.length : 0} warn={warned > 0} /></span>
          <span class="score"><b><Counter value={passed} /></b><span class="muted">of {checks.length}</span></span>
        </div>
        <div class="checks">
          <h2>{warned > 0 ? 'Check the device' : passed === checks.length ? 'Device healthy' : 'Device running'}</h2>
          <ul>
            {#each checks as c (c.id)}
              <li>
                <span class="mark {c.state}" aria-hidden="true">{c.state === 'ok' ? '✓' : c.state === 'warn' ? '!' : '·'}</span>
                <span>{c.label}</span>
                {#if c.id === 'rest' && c.state === 'wait' && app.locate?.health?.rest}
                  <button class="save" onclick={saveReference}>save as reference</button>
                {:else}
                  <span class="muted detail">{c.detail}</span>
                {/if}
              </li>
            {/each}
          </ul>
        </div>
      </article>

      <article class="tile session" style="--i:2">
        <h2>This session</h2>
        <div class="stats">
          <div><b><Counter value={total} /></b><span class="muted">steps heard</span></div>
          <div><b><Counter value={rate} digits={1} /></b><span class="muted">samples a second</span></div>
        </div>
        <div class="split" role="img" aria-label={`${sides.left} left, ${sides.right} right, ${sides.same} front, back or far`}>
          {#if total}
            <i style:flex-grow={sides.left} class="l"></i><i style:flex-grow={sides.same} class="n"></i><i style:flex-grow={sides.right} class="r"></i>
          {:else}<i class="empty" style:flex-grow={1}></i>{/if}
        </div>
        <div class="keys">
          <span><i class="l"></i>left <b><Counter value={sides.left} /></b></span>
          <span><i class="n"></i>front, back or far <b><Counter value={sides.same} /></b></span>
          <span><i class="r"></i>right <b><Counter value={sides.right} /></b></span>
        </div>
      </article>

      <article class="tile heatmap" style="--i:3">
        <h2>Vibration heat map <span class="unit">Hz</span><span class="scale" aria-hidden="true">quiet <i></i> strong</span></h2>
        <div class="fill"><HeatMap /></div>
      </article>

      <article class="tile vib" style="--i:4">
        <h2>Vibration</h2>
        <div class="fill"><VibrationLine /></div>
      </article>

      <article class="tile results" style="--i:5">
        <h2>Tested so far</h2>
        <div class="fill box"><ResultsTile /></div>
      </article>
    </div>
  {/if}
</section>

<style>
  .home {
    position: relative;
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
    padding: 14px 22px 20px;
    background: radial-gradient(120% 90% at 50% 0%, var(--panel2) 0%, var(--bg) 62%);
    overflow: auto;
  }
  .top {
    display: flex;
    align-items: center;
    gap: 10px;
    position: relative;
    z-index: 5;
    min-height: 34px;
  }
  .top .brand {
    padding: 0;
    font-weight: 700;
    letter-spacing: 0.32em;
    font-size: 13px;
  }
  .grow {
    flex: 1;
  }
  .badge {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.1em;
    padding: 3px 10px;
    border-radius: 20px;
    color: var(--warn);
    border: 1px solid var(--warn);
  }
  .ghost {
    background: transparent;
    border: 1px solid var(--line);
    border-radius: 20px;
    padding: 5px 14px;
    color: var(--muted);
    display: inline-flex;
    gap: 8px;
    align-items: center;
  }
  .ghost:hover {
    color: var(--text);
  }
  .menu {
    position: absolute;
    right: 0;
    top: 42px;
    display: grid;
    grid-template-columns: repeat(3, 120px);
    gap: 6px 18px;
    padding: 16px 18px;
    border-radius: 18px;
    background: var(--panel);
    border: 1px solid var(--line);
    box-shadow: 0 18px 50px rgba(0, 0, 0, 0.35);
    animation: pop 0.22s cubic-bezier(0.2, 0.9, 0.3, 1.1);
  }
  .menu h3 {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
    margin-bottom: 6px;
  }
  .menu button {
    display: block;
    width: 100%;
    text-align: left;
    background: none;
    border: 0;
    border-radius: 8px;
    padding: 6px 8px;
  }
  .menu button:hover {
    background: var(--panel2);
  }
  .menufoot {
    grid-column: 1 / -1;
    display: flex;
    gap: 8px;
    border-top: 1px solid var(--line);
    padding-top: 8px;
  }

  /* ---------------------------------------------------------------- the connect stage */
  .stage {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 22px;
    min-height: 420px;
  }
  .orb {
    position: relative;
    width: min(44vh, 340px);
    aspect-ratio: 1;
    border: 0;
    border-radius: 50%;
    background: none;
    padding: 0;
    transition: transform 0.35s cubic-bezier(0.2, 0.9, 0.3, 1.2);
  }
  .orb:hover:not(:disabled) {
    transform: scale(1.035);
  }
  .orb:active:not(:disabled) {
    transform: scale(0.97);
  }
  .orb:disabled {
    opacity: 1;
    cursor: progress;
  }
  .coreBig {
    display: block;
    width: 100%;
    height: 100%;
    view-transition-name: rz-core;
  }
  .orbText {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    font-size: 23px;
    font-weight: 600;
    letter-spacing: 0.02em;
  }
  .hint {
    margin: 0;
    color: var(--muted);
    display: flex;
    align-items: center;
    gap: 8px;
    min-height: 22px;
    text-align: center;
  }

  /* ---------------------------------------------------------------- the bento grid */
  .bento {
    flex: 1;
    min-height: 620px;
    margin-top: 12px;
    display: grid;
    gap: 14px;
    grid-template-columns: repeat(12, minmax(0, 1fr));
    grid-template-rows: minmax(190px, 0.9fr) minmax(190px, 1.15fr) minmax(210px, 1.05fr);
    grid-template-areas:
      'radar radar radar radar radar health health health health session session session'
      'radar radar radar radar radar heat heat heat heat heat heat heat'
      'vib vib vib vib vib vib vib results results results results results';
  }
  .tile {
    min-width: 0;
    min-height: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 15px 17px;
    border-radius: 22px;
    background: var(--panel);
    border: 1px solid color-mix(in srgb, var(--line) 60%, transparent);
    box-shadow:
      0 1px 0 rgba(255, 255, 255, 0.03) inset,
      0 10px 34px rgba(0, 0, 0, 0.18);
    animation: pop 0.65s cubic-bezier(0.2, 0.85, 0.25, 1.05) both;
    animation-delay: calc(140ms + var(--i) * 85ms);
  }
  .radar {
    grid-area: radar;
  }
  .health {
    grid-area: health;
    flex-direction: row;
    align-items: center;
    gap: 18px;
  }
  .session {
    grid-area: session;
  }
  .heatmap {
    grid-area: heat;
  }
  .vib {
    grid-area: vib;
  }
  .results {
    grid-area: results;
  }
  .tile h2 {
    font-size: 12.5px;
    font-weight: 600;
    text-transform: none;
    letter-spacing: 0;
    color: var(--muted);
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .fill {
    flex: 1;
    min-height: 0;
    position: relative;
  }
  .box {
    container: results / size;
  }
  .unit {
    font-weight: 400;
    font-size: 11px;
  }
  .scale {
    margin-left: auto;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-weight: 400;
    font-size: 11px;
  }
  .scale i {
    width: 70px;
    height: 7px;
    border-radius: 4px;
    background: linear-gradient(90deg, var(--heat-0), var(--heat-1), var(--heat-2));
  }
  .answer {
    display: flex;
    flex-direction: column;
    gap: 6px;
    height: 64px; /* always two lines, so the radar never changes size */
  }
  .answer b {
    font-size: 34px;
    line-height: 1.05;
    letter-spacing: 0.01em;
    padding-left: 14px;
    border-left: 5px solid var(--side-none);
    border-radius: 3px;
    transition: border-color 0.3s;
  }
  .answer.l b {
    border-color: var(--side-left);
  }
  .answer.r b {
    border-color: var(--side-right);
  }
  .answer .muted {
    font-size: 12.5px;
  }
  .ring {
    position: relative;
    flex: none;
    height: 100%;
    max-height: 158px;
    aspect-ratio: 1;
  }
  .coreSmall {
    display: block;
    width: 100%;
    height: 100%;
    view-transition-name: rz-core;
  }
  .score {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    line-height: 1;
    gap: 4px;
  }
  .score b {
    font-size: 34px;
  }
  .score .muted {
    font-size: 11.5px;
  }
  .checks {
    flex: 1;
    min-width: 0;
  }
  .checks h2 {
    color: var(--text);
    font-size: 15px;
    margin-bottom: 8px;
  }
  .checks ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: 12.5px;
  }
  .checks li {
    display: grid;
    grid-template-columns: 18px auto 1fr;
    gap: 6px;
    align-items: center;
    white-space: nowrap;
  }
  .detail {
    text-align: right;
    font-size: 11.5px;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .save {
    justify-self: end;
    border: 0;
    border-radius: 10px;
    padding: 1px 9px;
    font-size: 11.5px;
    color: var(--muted);
  }
  .mark {
    width: 16px;
    height: 16px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    font-size: 10.5px;
    font-weight: 700;
    color: var(--bg);
    background: var(--line2);
  }
  .mark.ok {
    background: var(--ok);
  }
  .mark.warn {
    background: var(--warn);
  }
  .stats {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
    flex: 1;
    align-items: center;
  }
  .stats b {
    display: block;
    font-size: 30px;
    line-height: 1.1;
  }
  .stats .muted {
    font-size: 11.5px;
  }
  .split {
    display: flex;
    gap: 2px;
    height: 12px;
  }
  .split i {
    flex-basis: 0;
    transition: flex-grow 0.6s cubic-bezier(0.2, 0.8, 0.3, 1);
  }
  .split i:first-child {
    border-radius: 4px 0 0 4px;
  }
  .split i:last-child {
    border-radius: 0 4px 4px 0;
  }
  i.l {
    background: var(--side-left);
  }
  i.r {
    background: var(--side-right);
  }
  i.n {
    background: var(--side-none);
  }
  i.empty {
    background: var(--line);
    border-radius: 4px !important;
  }
  .keys {
    display: flex;
    flex-wrap: wrap;
    gap: 2px 12px;
    font-size: 11.5px;
    color: var(--muted);
  }
  .keys span {
    display: inline-flex;
    gap: 5px;
    align-items: center;
  }
  .keys i {
    width: 9px;
    height: 9px;
    border-radius: 2px;
  }
  .keys b {
    color: var(--text);
    font-weight: 600;
  }

  @keyframes pop {
    from {
      opacity: 0;
      transform: translateY(14px) scale(0.965);
    }
    to {
      opacity: 1;
      transform: none;
    }
  }
  @media (max-width: 1050px) {
    .bento {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      grid-template-rows: none;
      grid-auto-rows: minmax(230px, auto);
      grid-template-areas:
        'radar radar'
        'health session'
        'heat heat'
        'vib vib'
        'results results';
    }
    .radar {
      min-height: 420px;
    }
  }
  @media (max-width: 620px) {
    .bento {
      grid-template-columns: minmax(0, 1fr);
      grid-template-areas: 'radar' 'health' 'session' 'heat' 'vib' 'results';
    }
    .menu {
      grid-template-columns: 1fr;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .tile,
    .menu {
      animation: none;
    }
  }
</style>
