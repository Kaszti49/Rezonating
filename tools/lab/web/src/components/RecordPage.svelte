<script lang="ts">
  // Record page (WEB_API.md section 9): data root, session form, Start / Stop, progress and loss, live labels,
  // phone marker, result. The `recording` and `label` WebSocket events (store) drive everything while recording.
  import { untrack } from 'svelte';
  import DataRootCard from './DataRootCard.svelte';
  import RecordForm from './RecordForm.svelte';
  import LabelPanel from './LabelPanel.svelte';
  import MarkerPanel from './MarkerPanel.svelte';
  import RecordResult from './RecordResult.svelte';
  import { api, ApiError } from '../lib/api';
  import { app } from '../lib/store.svelte';
  import { recForm } from '../lib/recform.svelte';
  import { fmtBytes, fmtElapsed, fmtFixed, fmtHostLoss, fmtInt } from '../lib/format';
  import type { RecordOptions, RecordResult as Result } from '../lib/types';

  let options = $state.raw<RecordOptions | null>(null);
  let optErr = $state('');
  let stopping = $state(false);
  let stopErr = $state('');
  let stopResult = $state.raw<Result | null>(null);
  /** Persons of the running session (the form may be edited meanwhile; marks may only use these). */
  let sessionPersons = $state<string[]>([]);

  const rec = $derived(app.recording);
  const recState = $derived(rec?.state ?? 'idle');
  const connState = $derived(app.connection?.state ?? 'disconnected');
  const active = $derived(app.recActive);
  const result = $derived(recState === 'idle' ? (rec?.last ?? stopResult) : null);
  const fresh = $derived(result !== null && stopResult?.session === result.session);

  async function loadOptions(): Promise<void> {
    try {
      options = await api.recOptions();
      optErr = '';
    } catch (e) {
      optErr = e instanceof ApiError ? e.message : String(e);
    }
  }

  // Load on open, after a connect or disconnect, and when a recording starts or ends.
  $effect(() => {
    void connState;
    void recState;
    untrack(() => void loadOptions());
  });

  // Remember who may be marked in the running session (from the form as it was at Start).
  $effect(() => {
    const s = rec?.session;
    if (recState === 'recording' && s) untrack(() => (sessionPersons = recForm.persons.slice()));
  });

  async function stop(): Promise<void> {
    stopping = true;
    stopErr = '';
    app.stopRequested = true;
    try {
      stopResult = await api.recStop();
    } catch (e) {
      app.stopRequested = false;
      stopErr = e instanceof ApiError ? e.message : String(e);
    } finally {
      stopping = false;
    }
  }

  function nCh(stream: string): number {
    return options?.node?.streams.find((s) => s.name === stream)?.n_ch ?? (stream === 'accel' ? 3 : 2);
  }
  function nominal(stream: string): number {
    return options?.node?.streams.find((s) => s.name === stream)?.nominal_hz ?? 2000;
  }
</script>

<div class="stack">
  {#if optErr}<div class="inline-err" role="alert">{optErr} <button onclick={loadOptions}>Retry</button></div>{/if}

  {#if active && rec}
    <section class="card">
      <header>
        <h2>Recording</h2>
        <span class="dot rec on"></span>
        <span class="mono">{rec.session ?? '…'}</span>
        {#if rec.protocol}<span class="chip">{rec.protocol}</span>{/if}
        {#if recState !== 'recording'}<span class="chip warn">{recState}</span>{/if}
        <span class="grow"></span>
        <span class="bigclock" aria-label="elapsed time">{fmtElapsed(rec.elapsed_s)}</span>
        <button class="danger" onclick={stop} disabled={stopping || recState !== 'recording'}>
          {stopping || recState === 'stopping' || recState === 'finalizing' ? 'Finishing…' : 'Stop recording'}
        </button>
      </header>
      {#if stopping}<div class="muted">Draining the node, closing and validating the files, moving them to the data root (usually 1-3 s).</div>{/if}
      {#if stopErr}<div class="inline-err" role="alert">{stopErr}</div>{/if}
      <div style="overflow-x:auto">
        <table>
          <thead>
            <tr>
              <th>stream</th>
              <th>file</th>
              <th class="r">on disk</th>
              <th class="r">≈ s</th>
              <th class="r">size</th>
              <th class="r">backlog</th>
              <th class="r" title="lost on the node">loss device</th>
              <th class="r" title="lost between node and server">link</th>
              <th class="r" title="sent but never arrived; N+ = lower bound while live">host</th>
            </tr>
          </thead>
          <tbody class="mono">
            {#each rec.streams as s (s.stream)}
              {@const l = s.loss}
              <tr>
                <td>{s.stream}</td>
                <td class="wrap">{s.file}</td>
                <td class="r">{fmtInt(s.frames_written)}</td>
                <td class="r">{fmtFixed(s.frames_written / nominal(s.stream), 1)}</td>
                <td class="r">{fmtBytes(s.frames_written * nCh(s.stream) * 4)}</td>
                <td class="r" title="frames received but not yet written ({s.queue_depth} packets)">{fmtInt(s.frames_received - s.frames_written)}</td>
                {#if l}
                  <td class="r" class:lossbad={l.device > 0}>{fmtInt(l.device)}</td>
                  <td class="r" class:lossbad={l.link > 0}>{fmtInt(l.link)}</td>
                  <td class="r" class:lossbad={l.host > 0}>{fmtHostLoss(l.host, l.host_exact !== false)}</td>
                {:else}
                  <td class="r muted" colspan="3">waiting for the node's first window</td>
                {/if}
              </tr>
              {#if s.overflow_packets > 0 || s.rejected_packets > 0 || s.error}
                <tr>
                  <td></td>
                  <td colspan="8">
                    <div class="inline-err" role="alert">
                      {#if s.error}<strong>Writer error:</strong> {s.error}.{/if}
                      {#if s.overflow_packets > 0}<strong>The disk cannot keep up:</strong> {fmtInt(s.overflow_packets)} packets dropped by the recorder (zeros in the file, counted as host loss).{/if}
                      {#if s.rejected_packets > 0}{fmtInt(s.rejected_packets)} packets rejected.{/if}
                    </div>
                  </td>
                </tr>
              {/if}
              {#if l?.protocol_bug}<tr><td></td><td colspan="8"><span class="chip err">protocol bug: host loss came out negative</span></td></tr>{/if}
            {/each}
          </tbody>
        </table>
      </div>
      {#if rec.marker_error}<div class="banner" style="margin-top:8px">Phone marker: {rec.marker_error}</div>{/if}
    </section>
  {:else}
    {#if result}<RecordResult {result} {fresh} />{/if}
    <DataRootCard root={options?.data_root ?? null} onchanged={loadOptions} />
    {#if options}
      <RecordForm {options} />
    {:else if !optErr}
      <div class="empty">Loading the recorder options…</div>
    {/if}
  {/if}

  <div class="grid2">
    <LabelPanel persons={active ? sessionPersons : recForm.persons} />
    <MarkerPanel />
  </div>
</div>
