<script lang="ts">
  // Locate: which side did a step come from? First, else much louder, else front/back/far. WEB_API.md section 15.
  import { app } from '../lib/store.svelte';
  import { locateApi, REASON_TEXT, SIDE_WORD } from '../lib/locate';
  import LocateRadar from './LocateRadar.svelte';

  let ripples = $state(true);

  const st = $derived(app.locate);
  const steps = $derived(app.locateSteps);
  const last = $derived(steps.length ? steps[steps.length - 1] : null);
  const connected = $derived(app.connection?.state === 'connected');
  const h = $derived(st?.health ?? null);

  async function swapSides(): Promise<void> {
    await app.run('locate', async () => (app.locate = await locateApi.swap(!(st?.swap_sides ?? false))));
  }
  async function saveBaseline(): Promise<void> {
    await app.run('locate', async () => (app.locate = await locateApi.saveBaseline()));
  }
  async function clearTrail(): Promise<void> {
    await app.run('locate', async () => (app.locate = await locateApi.clear()));
    app.locateSteps = [];
  }
</script>

<section class="locate">
  <div class="stage">
    <LocateRadar {ripples} />
    {#if !connected}
      <div class="overlay">
        <p>No node connected.</p>
        <p class="muted">Connect on the Home or Device page: the S3 rig on its USB port, or the Simulator.</p>
      </div>
    {/if}
  </div>

  <aside class="side">
    <div class="card">
      <div class="sideword" class:l={last?.side === 'left'} class:r={last?.side === 'right'}>{last ? SIDE_WORD[last.side] : '–'}</div>
      {#if last}
        <dl>
          <dt>Why</dt>
          <dd>{REASON_TEXT[last.reason]}</dd>
          <dt>This walk</dt>
          <dd>{last.walk_steps >= 2 ? SIDE_WORD[last.walk_side] : 'needs 2 steps'}</dd>
          <dt>Loudness</dt>
          <dd>ch0 {Math.round(last.amp[0])}, ch1 {Math.round(last.amp[1])} (ratio {last.ratio.toFixed(2)})</dd>
          <dt>Time gap</dt>
          <dd>{last.reason === 'first' ? `${SIDE_WORD[last.side].toLowerCase()} heard it ${Math.round(last.lead_s * 1e6)} µs first` : `${Math.round(last.tau_s * 1e6)} µs (not clear)`}</dd>
        </dl>
      {:else}
        <p class="muted">Waiting for a step…</p>
      {/if}
    </div>

    <div class="card">
      <header><h2>Rig health</h2></header>
      <p class="small">
        Geophones alike {h?.agree != null ? `${Math.round(100 * h.agree)} % of ${h.agree_n}` : '–'} · quiet level
        {h?.quiet != null ? Math.round(h.quiet) : '–'} · rest {h?.rest ? h.rest.map((v) => Math.round(v)).join(' / ') : '–'}
      </p>
      {#each h?.warnings ?? [] as w (w)}<p class="small note">{w}</p>{/each}
      <div class="row"><button onclick={saveBaseline} disabled={!connected}>Save as the good state</button></div>
      <p class="small muted">
        {h?.baseline ? `Saved ${h.baseline.saved ?? ''}: rest ${h.baseline.rest.map((v) => Math.round(v)).join(' / ')}, quiet ${Math.round(h.baseline.quiet)}.` : 'No good state saved yet: the rest level is not checked.'}
      </p>
    </div>

    <div class="card">
      <header><h2>Settings</h2></header>
      <div class="row">
        <button onclick={swapSides}>Swap left and right{st?.swap_sides ? ' (on)' : ''}</button>
        <label><input type="checkbox" bind:checked={ripples} /> ripples</label>
        <button onclick={clearTrail}>Clear</button>
      </div>
      <p class="small muted">
        Heard first on one side: that side. No clear timing, but 1.5 times louder on one side: that side. Else front, back
        or too far (two geophones on one line can't tell which). The case decides which side is which: swap when it is
        turned round. On the radar, solid dots were clearly first, hollow ones were not.
      </p>
    </div>

    <div class="card">
      <header><h2>Counts</h2></header>
      <p class="small">
        LEFT {st?.sides?.left ?? 0} · RIGHT {st?.sides?.right ?? 0} · FRONT, BACK or FAR {st?.sides?.same ?? 0}
      </p>
      <p class="small">Steps {st?.steps ?? 0} · skipped: lost samples {st?.skipped_gaps ?? 0}, clipped {st?.skipped_clipped ?? 0}</p>
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
  .stage {
    position: relative;
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 8px;
    min-height: 480px;
    padding: 10px;
    overflow: hidden;
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
  .sideword {
    font-size: 36px;
    font-weight: 800;
    text-align: center;
    line-height: 1.1;
    margin: 4px 0 8px;
    border-bottom: 4px solid var(--side-none);
    padding-bottom: 8px;
  }
  .sideword.l {
    border-color: var(--side-left);
  }
  .sideword.r {
    border-color: var(--side-right);
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
  .note {
    color: var(--warn);
  }
  .row {
    margin-top: 6px;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
  }
  @media (max-width: 900px) {
    .locate {
      grid-template-columns: 1fr;
    }
  }
</style>
