<script lang="ts">
  // Guided rig checks for a freshly wired node (WEB_API.md section 11). The server owns the state; this card shows the
  // `rigcheck` event and sends run / continue / cancel.
  import { onMount } from 'svelte';
  import { app } from '../lib/store.svelte';
  import { ApiError } from '../lib/api';
  import { REPORT_URL, rigApi, type RigCheck, type RigCheckId } from '../lib/rigcheck';

  const view = $derived(app.rigcheck);
  const checks = $derived(view?.checks ?? []);
  const connected = $derived(app.connection?.state === 'connected');
  const running = $derived(view?.running === true);
  const canRun = $derived(connected && !running && !app.recActive);
  const current = $derived(checks.find((c) => c.id === view?.current) ?? null);
  const hasResults = $derived(checks.some((c) => c.state === 'pass' || c.state === 'fail' || c.state === 'error'));
  const passed = $derived(checks.filter((c) => c.state === 'pass').length);
  const finished = $derived(checks.filter((c) => c.state === 'pass' || c.state === 'fail' || c.state === 'error').length);
  let open = $state<Record<string, boolean>>({});
  let copied = $state(false);

  onMount(() => {
    if (!app.rigcheck) rigApi.view().then((v) => (app.rigcheck = v)).catch(() => {});
  });

  async function act(fn: () => Promise<unknown>): Promise<void> {
    try {
      const v = await fn();
      if (v && typeof v === 'object' && (v as { type?: string }).type === 'rigcheck') app.rigcheck = v as typeof app.rigcheck;
    } catch (e) {
      app.toast(e instanceof ApiError || e instanceof Error ? e.message : String(e), 'error');
    }
  }

  const runOne = (id: RigCheckId) => act(() => rigApi.run([id]));
  const runAll = () => act(() => rigApi.run());
  const cont = () => act(() => rigApi.confirm());
  const cancel = () => act(() => rigApi.cancel());

  async function copyReport(): Promise<void> {
    try {
      await navigator.clipboard.writeText(await rigApi.report());
      copied = true;
      setTimeout(() => (copied = false), 1500);
    } catch (e) {
      app.toast(e instanceof Error ? e.message : String(e), 'error');
    }
  }

  function chip(c: RigCheck): { cls: string; text: string } {
    switch (c.state) {
      case 'pass':
        return { cls: 'chip ok', text: 'pass' };
      case 'fail':
        return { cls: 'chip err', text: 'fail' };
      case 'error':
        return { cls: 'chip err', text: 'error' };
      case 'running':
        return { cls: 'chip warn', text: 'running' };
      case 'waiting':
        return { cls: 'chip warn', text: 'waiting for you' };
      case 'cancelled':
        return { cls: 'chip', text: 'cancelled' };
      default:
        return { cls: 'chip', text: 'not run' };
    }
  }
</script>

<section class="card rig">
  <header>
    <h2>Rig checks</h2>
    {#if hasResults}<span class="muted">{passed} of {finished} passed</span>{/if}
    {#if view?.sim}<span class="chip">simulator: person steps skipped, taps injected</span>{/if}
    <span class="grow"></span>
    {#if running}
      <button class="danger" onclick={cancel}>Cancel</button>
    {:else}
      <button class="primary" disabled={!canRun} onclick={runAll}>Run all</button>
    {/if}
    <button disabled={!hasResults} onclick={copyReport}>{copied ? 'Copied' : 'Copy report'}</button>
    {#if hasResults}
      <a class="button" href={REPORT_URL} download>Download report</a>
    {:else}
      <button disabled>Download report</button>
    {/if}
  </header>

  {#if !connected}
    <div class="empty">Connect a node to run the rig checks.</div>
  {:else if app.recActive}
    <div class="empty">A recording runs: rig checks are off until it stops.</div>
  {/if}

  {#if current?.prompt}
    <div class="prompt" class:wait={view?.awaiting_confirm} aria-live="polite">
      <strong>{current.title}:</strong>
      {current.prompt}
      {#if view?.awaiting_confirm}
        <button class="primary" onclick={cont}>Continue</button>
      {/if}
    </div>
  {/if}

  <ol class="checks">
    {#each checks as c (c.id)}
      {@const ch = chip(c)}
      <li class:active={view?.current === c.id}>
        <div class="head">
          <span class="title">{c.title}</span>
          <span class={ch.cls}>{ch.text}</span>
          <span class="grow"></span>
          <button class="link" onclick={() => (open[c.id] = !open[c.id])}>{open[c.id] ? 'Hide steps' : 'Steps'}</button>
          <button disabled={!canRun} onclick={() => runOne(c.id)}>Run</button>
        </div>
        {#if open[c.id] || view?.current === c.id}
          <ol class="guide muted">
            {#each c.guide as step, i (i)}<li>{step}</li>{/each}
          </ol>
        {/if}
        {#if c.detail}<div class="mono detail wrap">{c.detail}</div>{/if}
        {#if c.limit}<div class="muted small">limit: {c.limit}</div>{/if}
      </li>
    {/each}
  </ol>

  {#if view?.report_path}
    <div class="muted small wrap">Report saved: <span class="mono">{view.report_path}</span></div>
  {:else if view?.report_error}
    <div class="muted small wrap">Report not saved: {view.report_error} (download or copy it instead)</div>
  {/if}
</section>

<style>
  .rig {
    margin-top: 14px;
  }
  .checks {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 8px;
  }
  .checks > li {
    border: 1px solid var(--line);
    border-radius: 6px;
    padding: 6px 10px;
  }
  .checks > li.active {
    border-color: var(--warn);
  }
  .head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px 10px;
  }
  .head .grow {
    flex: 1;
  }
  .title {
    font-weight: 600;
  }
  .guide {
    margin: 6px 0 2px;
    padding-left: 20px;
    font-size: 13px;
  }
  .detail {
    margin-top: 4px;
    font-size: 12.5px;
  }
  .small {
    font-size: 12px;
  }
  .prompt {
    margin: 0 0 10px;
    padding: 8px 12px;
    border-radius: 8px;
    border: 1px solid var(--line2);
    display: flex;
    flex-wrap: wrap;
    gap: 6px 10px;
    align-items: center;
  }
  .prompt.wait {
    border-color: var(--warn);
  }
  button.link {
    background: none;
    border: none;
    color: var(--muted);
    text-decoration: underline;
    padding: 0 4px;
  }
  a.button {
    display: inline-block;
    padding: 4px 10px;
    border: 1px solid var(--line2);
    border-radius: 6px;
    color: inherit;
    text-decoration: none;
  }
</style>
