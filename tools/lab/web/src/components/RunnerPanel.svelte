<script lang="ts">
  // Protocol runner (WEB_API.md section 10). The server owns the steps and counters (a reload shows the same state);
  // this panel shows them and sends next / back / skip / goto. Space (Live labels) or the phone marks the passes: their
  // label, person, pace and shoes come from the current step, and a finished mark counts as one pass.
  import { onMount } from 'svelte';
  import { api, ApiError } from '../lib/api';
  import { app } from '../lib/store.svelte';
  import type { RunnerStep, RunnerView } from '../lib/types';

  let { protocol }: { protocol: string | null } = $props();

  let busy = $state(false);
  let err = $state('');
  let nowMs = $state(performance.now());

  const r = $derived(app.runner);
  const on = $derived(r?.active === true);
  const recording = $derived(app.recording?.state === 'recording');
  const step = $derived(r && r.current !== null ? (r.steps[r.current] ?? null) : null);
  const moving = $derived(busy || r?.state === 'countdown' || r?.state === 'marking');
  const remaining = $derived.by(() => {
    const c = r?.countdown;
    if (!c) return null;
    const since = Math.max(0, (nowMs - app.runnerAt) / 1000);
    return Math.max(0, Math.min(c.remaining_s, c.remaining_s - since));
  });

  // Tick while a countdown runs (the server ends the label; this only redraws the seconds).
  $effect(() => {
    if (!r?.countdown) return;
    nowMs = performance.now();
    const id = window.setInterval(() => (nowMs = performance.now()), 200);
    return () => window.clearInterval(id);
  });

  onMount(() => {
    void (async () => {
      try {
        app.applyRunner(await api.runner());
      } catch {
        /* the `runner` event fills it anyway */
      }
    })();
  });

  async function act(fn: () => Promise<RunnerView>): Promise<void> {
    busy = true;
    err = '';
    try {
      app.applyRunner(await fn());
    } catch (e) {
      err = e instanceof ApiError ? e.message : String(e);
    } finally {
      busy = false;
    }
  }

  /** The same as Space: start or end a mark (the server takes the tags from the current step). */
  async function toggle(): Promise<void> {
    err = '';
    try {
      const res = await api.mark('toggle');
      app.applyLabel({ action: res.action, mark: res.mark });
    } catch (e) {
      err = e instanceof ApiError ? e.message : String(e);
    }
  }

  function tags(s: RunnerStep): string {
    if (s.kind === 'timed') return `${s.label}, ${fmtSeconds(s.duration_s)}`;
    const parts = [s.person ?? 'nobody', s.pace ? `${s.pace} pace` : null, s.shoes === null ? null : s.shoes ? 'shoes on' : 'shoes off'];
    return parts.filter(Boolean).join(' · ');
  }

  function fmtSeconds(v: number | null): string {
    if (v === null) return '—';
    return v >= 10 ? `${Math.round(v)} s` : `${v.toFixed(1)} s`;
  }

  const STATUS_TEXT: Record<string, string> = {
    pending: 'to do',
    active: 'now',
    done: 'done',
    incomplete: 'incomplete',
    skipped: 'skipped',
  };
</script>

<section class="card">
  <header>
    <h2>Protocol runner</h2>
    {#if on && r}
      <span class="chip">{r.protocol}</span>
      {#if r.overall}<span class="mono" title="passes marked / passes in the protocol (all persons)">overall {r.overall.done} / {r.overall.target}</span>{/if}
      {#each Object.entries(r.per_person) as [p, c] (p)}
        <span class="chip {c.done >= c.target ? 'ok' : ''}" title="passes of {p}">{p} {c.done}/{c.target}</span>
      {/each}
    {/if}
    <span class="grow"></span>
    {#if on}
      <button onclick={() => act(api.runnerStop)} disabled={moving} title="Leave the runner: marks take the label form's fields again">Stop runner</button>
    {/if}
  </header>

  {#if !recording}
    <div class="muted">The runner works while a recording runs. Tick "run it step by step" in the form, or start it here once recording.</div>
  {:else if !on}
    <div class="row" style="align-items:center">
      <span class="muted">Off: marks take the fields of the label form.</span>
      <button class="primary" onclick={() => act(() => api.runnerStart())} disabled={busy}>Start {protocol ?? 'the protocol'} step by step</button>
    </div>
  {:else if r}
    {#if r.state === 'finished'}
      <div class="markbox" role="status">
        <span class="big">All steps done</span>
        <span class="muted">Stop the recording, or go back to a step to add passes.</span>
      </div>
    {:else if step}
      <div class="markbox" class:open={r.state !== 'ready'} role="status" aria-live="polite">
        <span class="mono muted">step {step.index + 1} / {r.steps.length}</span>
        <span class="big">{tags(step)}</span>
        {#if step.kind === 'passes'}
          <span class="mono" aria-label="passes of this step">pass {Math.min(step.done + 1, step.target)} of {step.target} · {step.done} done</span>
        {/if}
        <span class="grow" style="flex:1"></span>
        {#if r.state === 'countdown'}
          <span class="bigclock" aria-label="seconds left">{remaining !== null ? Math.ceil(remaining) : '—'} s</span>
          <button onclick={() => act(() => api.runnerMove('cancel'))} disabled={busy}>Cancel countdown</button>
        {:else if step.kind === 'timed'}
          <span>Press <kbd>Space</kbd> to start the {fmtSeconds(step.duration_s)} countdown</span>
          <button class="primary" onclick={toggle}>Start countdown</button>
        {:else if r.state === 'marking'}
          <span class="dot rec on"></span>
          <span>Press <kbd>Space</kbd> to end the pass</span>
          <button onclick={toggle}>End pass</button>
        {:else}
          <span>Press <kbd>Space</kbd> to start the pass</span>
          <button class="primary" onclick={toggle}>Start pass</button>
        {/if}
      </div>
      {#if step.instructions}<div class="muted" style="margin:-4px 0 8px">{step.instructions}</div>{/if}
      {#if step.done >= step.target && r?.state === 'ready'}
        <div class="banner" style="margin:0 0 8px">This step is complete ({step.done} of {step.target}): a new mark is refused. Delete one of its labels to redo it, or go to another step.</div>
      {/if}
    {/if}

    <div class="row" style="align-items:center">
      <button onclick={() => act(() => api.runnerMove('back'))} disabled={moving || r.current === 0}>Back</button>
      <button onclick={() => act(() => api.runnerMove('next'))} disabled={moving || r.state === 'finished'} title="Go to the next step; this one stays incomplete if passes are missing">Next</button>
      <button onclick={() => act(() => api.runnerMove('skip'))} disabled={moving || r.state === 'finished'} title="Leave this step out (marked skipped)">Skip</button>
      {#if r.state === 'countdown' || r.state === 'marking'}<span class="muted">Finish the {r.state === 'countdown' ? 'countdown' : 'pass'} before moving.</span>{/if}
    </div>

    <div style="overflow-x:auto; margin-top:10px; max-height:320px; overflow-y:auto">
      <table>
        <thead>
          <tr>
            <th class="r">#</th>
            <th>person</th>
            <th>step</th>
            <th class="r">passes</th>
            <th>status</th>
            <th></th>
          </tr>
        </thead>
        <tbody class="mono">
          {#each r.steps as s (s.key)}
            <tr class:current={s.index === r.current}>
              <td class="r">{s.index + 1}</td>
              <td>{s.person ?? '—'}</td>
              <td>{s.kind === 'timed' ? tags(s) : `${s.id}`}</td>
              <td class="r">{s.done} / {s.target}</td>
              <td><span class="chip {s.status === 'done' ? 'ok' : s.status === 'incomplete' || s.status === 'skipped' ? 'warn' : ''}">{STATUS_TEXT[s.status] ?? s.status}</span></td>
              <td>
                {#if s.index !== r.current}
                  <button onclick={() => act(() => api.runnerGoto(s.index))} disabled={moving} aria-label="Go to step {s.index + 1}">Go</button>
                {/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
  {#if err}<div class="inline-err" role="alert" style="margin-top:8px">{err}</div>{/if}
</section>

<style>
  tr.current td {
    background: var(--panel2);
    font-weight: 600;
  }
</style>
