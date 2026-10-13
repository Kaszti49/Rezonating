<script lang="ts">
  import Scope from './Scope.svelte';
  import Psd from './Psd.svelte';
  import Spectrogram from './Spectrogram.svelte';
  import { app, chName, streamFs } from '../lib/store.svelte';
  import type { UnitName } from '../lib/types';

  const WINDOWS = [1, 2, 5, 10, 20, 30, 60];
  const UNITS: UnitName[] = ['counts', 'V', 'g'];

  const streams = $derived(app.hello?.streams ?? []);
  const connected = $derived(app.connection?.state === 'connected');
  const acquiring = $derived(app.status?.acquiring ?? false);

  // Pause: the head index of every stream at the moment of pausing.
  let frozen = $state<Record<number, number> | null>(null);
  let backS = $state(0);

  let selStream = $state(0);
  let selCh = $state(0);
  const analysed = $derived(streams.find((s) => s.id === selStream) ?? streams[0]);
  const chCount = $derived(analysed?.n_ch ?? 1);

  $effect(() => {
    // Keep the channel selection valid when the stream changes.
    if (selCh >= chCount) selCh = 0;
  });

  function pause(): void {
    const heads: Record<number, number> = {};
    for (const s of streams) {
      const ring = app.rings.get(s.id);
      heads[s.id] = ring && ring.hasData ? ring.head : (app.status?.streams.find((x) => x.id === s.id)?.head ?? 0);
    }
    backS = 0;
    frozen = heads;
  }
  function resume(): void {
    frozen = null;
    backS = 0;
  }

  const maxBack = $derived.by(() => {
    if (!frozen || !analysed) return 0;
    const head = frozen[analysed.id] ?? 0;
    return Math.max(0, Math.min(600, head / streamFs(analysed.id)) - app.windowS);
  });

  async function toggleAcq(): Promise<void> {
    if (acquiring) await app.stopAcq();
    else await app.startAcq();
  }
</script>

<div class="toolbar">
  <button class={acquiring ? 'danger' : 'primary'} disabled={!connected || app.busy !== null} onclick={toggleAcq}>
    {acquiring ? 'Stop acquisition' : 'Start acquisition'}
  </button>
  <label>
    Window
    <select value={app.windowS} onchange={(e) => app.setWindow(Number(e.currentTarget.value))}>
      {#each WINDOWS as w (w)}<option value={w}>{w} s</option>{/each}
    </select>
  </label>
  <span class="seg" role="group" aria-label="Units">
    {#each UNITS as u (u)}
      <button class:on={app.units === u} onclick={() => app.setUnits(u)}>{u}</button>
    {/each}
  </span>
  <button onclick={frozen ? resume : pause} disabled={streams.length === 0}>{frozen ? 'Resume live' : 'Pause'}</button>
  {#if frozen}
    <label style="flex:1; min-width:200px">
      Back
      <input type="range" min="0" max={maxBack} step="0.5" bind:value={backS} style="flex:1" aria-label="Scroll back in seconds" />
      <span class="num" style="min-width:64px; text-align:right">&minus;{backS.toFixed(1)} s</span>
    </label>
  {/if}
  <span class="grow" style="flex:1"></span>
  {#if !connected}
    <span class="chip warn">no node connected: use the Device page</span>
  {:else if !acquiring}
    <span class="chip">node idle: press Start acquisition</span>
  {/if}
</div>

{#if streams.length === 0}
  <div class="card empty">No streams yet. Connect a node (or the simulator) on the Device page.</div>
{:else}
  {#each streams as s (s.id)}
    <Scope stream={s} frozen={frozen ? (frozen[s.id] ?? null) : null} {backS} />
  {/each}

  <div class="toolbar">
    <label>
      Analyse stream
      <select bind:value={selStream}>
        {#each streams as s (s.id)}<option value={s.id}>{s.name}</option>{/each}
      </select>
    </label>
    <label>
      Spectrogram channel
      <select bind:value={selCh}>
        {#each { length: chCount } as _, c (c)}
          <option value={c}>{analysed ? chName(analysed.name, c) : c}</option>
        {/each}
      </select>
    </label>
  </div>

  {#if analysed}
    <div class="grid2">
      <Psd stream={analysed} frozen={frozen ? (frozen[analysed.id] ?? null) : null} {backS} />
      <Spectrogram stream={analysed} channel={selCh} frozen={frozen ? (frozen[analysed.id] ?? null) : null} {backS} />
    </div>
  {/if}
{/if}
