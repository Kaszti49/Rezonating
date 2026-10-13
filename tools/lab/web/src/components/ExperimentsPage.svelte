<script lang="ts">
  // Experiments page (Lab phase 7): pick sessions, split by session or person (never by window), run a model next to
  // the majority-class baseline, save the run under tools/lab/runs/, and draft an EXP note into 50 Experiments.
  import { onMount } from 'svelte';
  import { app } from '../lib/store.svelte';
  import { ApiError } from '../lib/api';
  import { datasetsApi, type DatasetList, type DatasetRow } from '../lib/datasets';
  import {
    experimentsApi,
    type DraftResult,
    type Job,
    type Model,
    type Options,
    type RunResult,
    type RunSummary,
    type Split,
    type Target,
  } from '../lib/experiments';
  import { fmtFixed, fmtInt } from '../lib/format';

  type Tri = '' | 'true' | 'false';

  let options = $state.raw<Options | null>(null);
  let pack = $state('footstep-id');
  let target = $state<Target>('person');
  let split = $state<Split>('session');
  let model = $state<Model>('logreg');
  let seed = $state(0);
  let testMode = $state<'groups' | 'fraction'>('fraction');
  let fraction = $state(0.25);
  let testGroups = $state.raw<Set<string>>(new Set());

  // session picker
  let fProtocol = $state('');
  let fFloor = $state('');
  let fPerson = $state('');
  let fSimulated = $state<Tri>('');
  let list = $state.raw<DatasetList | null>(null);
  let listError = $state<string | null>(null);
  let selected = $state.raw<Set<string>>(new Set());

  let job = $state.raw<Job | null>(null);
  let runError = $state<string | null>(null);
  let result = $state.raw<RunResult | null>(null);
  let runs = $state.raw<RunSummary[]>([]);
  let draftTitle = $state('');
  let draft = $state.raw<DraftResult | null>(null);
  let drafting = $state(false);

  const running = $derived(job?.state === 'running');
  const rows = $derived<DatasetRow[]>(list?.sessions ?? []);
  const chosen = $derived(rows.filter((r) => selected.has(r.session)));
  const personSplitForPerson = $derived(split === 'person' && target === 'person');
  const groupChoices = $derived(
    split === 'session' ? chosen.map((r) => r.session) : [...new Set(chosen.flatMap((r) => r.people))].sort(),
  );
  const canRun = $derived(
    !running &&
      !personSplitForPerson &&
      chosen.length >= 2 &&
      (testMode === 'fraction' ? fraction > 0 && fraction < 1 : testGroups.size > 0),
  );

  function msg(e: unknown): string {
    return e instanceof ApiError || e instanceof Error ? e.message : String(e);
  }

  async function loadSessions(): Promise<void> {
    listError = null;
    try {
      list = await datasetsApi.list({
        protocol: fProtocol || undefined,
        floor: fFloor || undefined,
        person: fPerson || undefined,
        simulated: fSimulated === '' ? undefined : fSimulated === 'true',
      });
      const names = new Set(list.sessions.filter((r) => r.valid).map((r) => r.session));
      selected = new Set([...selected].filter((s) => names.has(s)));
    } catch (e) {
      listError = msg(e);
    }
  }

  async function loadRuns(): Promise<void> {
    try {
      runs = (await experimentsApi.runs()).runs;
    } catch (e) {
      app.toast(`Runs: ${msg(e)}`);
    }
  }

  function toggle(set: Set<string>, key: string): Set<string> {
    const next = new Set(set);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    return next;
  }

  function selectAllValid(on: boolean): void {
    selected = on ? new Set(rows.filter((r) => r.valid).map((r) => r.session)) : new Set();
  }

  $effect(() => {
    // keep the explicit test groups inside the current choices (split kind or session choice changed)
    const allowed = new Set(groupChoices);
    if ([...testGroups].some((g) => !allowed.has(g))) testGroups = new Set([...testGroups].filter((g) => allowed.has(g)));
  });

  async function run(): Promise<void> {
    runError = null;
    draft = null;
    try {
      const { job: id } = await experimentsApi.run({
        pack,
        sessions: chosen.map((r) => r.session),
        split,
        target,
        model,
        seed,
        test_groups: testMode === 'groups' ? [...testGroups] : null,
        fraction: testMode === 'fraction' ? fraction : null,
      });
      job = { id, state: 'running', done: 0, total: chosen.length, stage: 'starting' };
      while (job.state === 'running') {
        await new Promise((r) => setTimeout(r, 400));
        job = await experimentsApi.job(id);
      }
      if (job.state === 'error') runError = job.error?.message ?? 'The run failed.';
      else if (job.result) {
        result = job.result;
        draftTitle = `${result.config.target} by ${result.config.split} split${result.simulated ? ' (sim)' : ''}`;
        await loadRuns();
      }
    } catch (e) {
      runError = msg(e);
      job = null;
    }
  }

  async function open(id: string): Promise<void> {
    try {
      result = await experimentsApi.detail(id);
      draft = null;
      draftTitle = `${result.config.target} by ${result.config.split} split${result.simulated ? ' (sim)' : ''}`;
    } catch (e) {
      app.toast(`Run ${id}: ${msg(e)}`);
    }
  }

  async function makeDraft(): Promise<void> {
    if (!result) return;
    drafting = true;
    try {
      draft = await experimentsApi.draft(result.run_id, draftTitle);
      if (draft.ok) {
        app.toast(`${draft.path} written`, 'info');
        await loadRuns();
      }
    } catch (e) {
      app.toast(`Draft: ${msg(e)}`);
    } finally {
      drafting = false;
    }
  }

  function heat(v: number, row: number[]): string {
    const total = row.reduce((a, b) => a + b, 0) || 1;
    return `background: color-mix(in srgb, var(--accent) ${Math.round((100 * v) / total)}%, transparent)`;
  }

  const pct = (v: number) => fmtFixed(v * 100, 1, ' %');

  onMount(async () => {
    try {
      options = await experimentsApi.options();
      if (options.packs.length && !options.packs.some((p) => p.id === pack)) pack = options.packs[0].id;
    } catch (e) {
      app.toast(`Experiments: ${msg(e)}`);
    }
    await Promise.all([loadSessions(), loadRuns()]);
  });
</script>

<div class="page">
  <section class="card">
    <header><h2>Experiment</h2><span class="muted small">split by session or person, never by window; the baseline is always shown</span></header>
    <div class="toolbar">
      <label>Pack
        <select bind:value={pack}>
          {#each options?.packs ?? [{ id: 'footstep-id', name: null, features: null }] as p (p.id)}<option value={p.id}>{p.id}</option>{/each}
        </select>
      </label>
      <label>Target
        <select bind:value={target}><option value="person">person</option><option value="pace">pace</option><option value="shoes">shoes</option></select>
      </label>
      <label>Split by
        <select bind:value={split}><option value="session">session</option><option value="person">person</option></select>
      </label>
      <label>Model
        <select bind:value={model}><option value="logreg">logistic regression</option><option value="rf">random forest</option></select>
      </label>
      <label>Seed <input type="number" min="0" step="1" bind:value={seed} style="width:6em" /></label>
      <label>Test
        <select bind:value={testMode}><option value="fraction">fraction of {split}s</option><option value="groups">chosen {split}s</option></select>
      </label>
      {#if testMode === 'fraction'}
        <label>Fraction <input type="number" min="0.05" max="0.95" step="0.05" bind:value={fraction} style="width:5em" /></label>
      {/if}
    </div>
    {#if personSplitForPerson}
      <p class="inline-err">A split by person cannot evaluate person identification: every test person would be unseen in training. Split by session, or choose target pace or shoes.</p>
    {/if}
    {#if testMode === 'groups'}
      <div class="groups">
        <span class="muted small">Test {split}s:</span>
        {#each groupChoices as g (g)}
          <label class="check"><input type="checkbox" checked={testGroups.has(g)} onchange={() => (testGroups = toggle(testGroups, g))} /> <span class="mono small">{g}</span></label>
        {:else}
          <span class="muted small">choose sessions first</span>
        {/each}
      </div>
    {/if}
  </section>

  <section class="card">
    <header>
      <h2>Sessions</h2>
      <span class="muted small">{chosen.length} chosen of {rows.length} shown; invalid sessions cannot be chosen</span>
      <span class="grow"></span>
      <button onclick={() => selectAllValid(true)}>All valid</button>
      <button onclick={() => selectAllValid(false)}>None</button>
    </header>
    <div class="toolbar">
      <label>Protocol
        <select bind:value={fProtocol} onchange={loadSessions}><option value="">any</option>{#each list?.facets.protocols ?? [] as v (v)}<option value={v}>{v}</option>{/each}</select>
      </label>
      <label>Floor
        <select bind:value={fFloor} onchange={loadSessions}><option value="">any</option>{#each list?.facets.floors ?? [] as v (v)}<option value={v}>{v}</option>{/each}</select>
      </label>
      <label>Person
        <select bind:value={fPerson} onchange={loadSessions}><option value="">any</option>{#each list?.facets.people ?? [] as v (v)}<option value={v}>{v}</option>{/each}</select>
      </label>
      <label>Simulated
        <select bind:value={fSimulated} onchange={loadSessions}><option value="">any</option><option value="false">real only</option><option value="true">simulated only</option></select>
      </label>
      <button onclick={loadSessions}>Refresh</button>
    </div>
    {#if listError}<p class="inline-err">{listError}</p>{/if}
    <div class="scroll">
      <table>
        <thead><tr><th></th><th>Session</th><th>People</th><th>Protocol</th><th>Floor</th><th class="r">Labels</th><th>State</th></tr></thead>
        <tbody>
          {#each rows as r (r.session)}
            <tr class:dim={!r.valid}>
              <td><input type="checkbox" disabled={!r.valid} checked={selected.has(r.session)} onchange={() => (selected = toggle(selected, r.session))} aria-label="choose {r.session}" /></td>
              <td class="mono">{r.session}</td>
              <td>{r.people.join(', ')}</td>
              <td>{r.protocol ?? ''}</td>
              <td>{r.floor ?? ''}</td>
              <td class="r num">{fmtInt(r.label_count)}</td>
              <td>
                {#if !r.valid}<span class="chip err" title={r.errors.join('\n')}>invalid</span>{/if}
                {#if r.simulated}<span class="chip warn">simulated</span>{/if}
              </td>
            </tr>
          {:else}
            <tr><td colspan="7" class="muted">No sessions (check the data root on the Datasets page).</td></tr>
          {/each}
        </tbody>
      </table>
    </div>
    <div class="runrow">
      <button class="primary" disabled={!canRun} onclick={run}>Run</button>
      {#if job && running}
        <progress max={job.total || 1} value={job.done}></progress>
        <span class="small muted">{job.done}/{job.total} sessions: {job.stage}</span>
      {/if}
      {#if runError}<span class="inline-err">{runError}</span>{/if}
    </div>
  </section>

  {#if result}
    {@const ev = result.result}
    <section class="card">
      <header>
        <h2>Result</h2>
        <span class="mono small">{result.run_id}</span>
        {#if result.simulated}<span class="chip warn big">SIMULATED DATA</span>{/if}
        {#if result.beats_baseline}<span class="chip ok">beats baseline</span>{:else}<span class="chip err">does not beat baseline</span>{/if}
      </header>
      {#if result.simulated}
        <p class="simbanner">SIMULATED DATA: these numbers come from simulated sessions and say nothing about a real floor.</p>
      {/if}
      <p class="small">
        Target <b>{result.config.target}</b>, split by <b>{result.config.split}</b>, model <b>{result.config.model}</b>, seed {result.config.seed}.
        Train: {result.split.train_sessions.join(', ')} ({fmtInt(ev.n_train)} windows). Test: {result.split.test_sessions.join(', ')} ({fmtInt(ev.n_test)} windows).
        Train people {result.split.train_people.join(', ') || '-'}; test people {result.split.test_people.join(', ') || '-'}.
      </p>
      {#if result.flags.length}
        <ul class="flags">{#each result.flags as f (f)}<li><span class="chip warn">flag</span> {f}</li>{/each}</ul>
      {/if}
      <div class="grid">
        <div>
          <h3>Model vs baseline</h3>
          <table>
            <thead><tr><th></th><th class="r">Accuracy</th><th class="r">Balanced accuracy</th></tr></thead>
            <tbody>
              <tr><td>{result.config.model}</td><td class="r num">{pct(ev.scores.accuracy)}</td><td class="r num">{pct(ev.scores.balanced_accuracy)}</td></tr>
              <tr><td>majority baseline</td><td class="r num">{pct(ev.baseline.accuracy)}</td><td class="r num">{pct(ev.baseline.balanced_accuracy)}</td></tr>
            </tbody>
          </table>
          <h3>Confusion (rows true, columns predicted)</h3>
          <table class="heat">
            <thead><tr><th>true \ pred</th>{#each ev.labels as l (l)}<th class="r">{l}</th>{/each}</tr></thead>
            <tbody>
              {#each ev.scores.confusion as row, i (i)}
                <tr><th>{ev.labels[i]}</th>{#each row as v, j (j)}<td class="r num" style={heat(v, row)}>{v}</td>{/each}</tr>
              {/each}
            </tbody>
          </table>
        </div>
        <div>
          <h3>Per class</h3>
          <table>
            <thead><tr><th>Class</th><th class="r">Precision</th><th class="r">Recall</th><th class="r">F1</th><th class="r">n</th></tr></thead>
            <tbody>
              {#each Object.entries(ev.scores.per_class) as [k, v] (k)}
                <tr><td>{k}</td><td class="r num">{pct(v.precision)}</td><td class="r num">{pct(v.recall)}</td><td class="r num">{pct(v.f1)}</td><td class="r num">{v.support}</td></tr>
              {/each}
            </tbody>
          </table>
          <h3>Per person</h3>
          {#if Object.keys(result.per_person).length}
            <table>
              <thead><tr><th>Person</th><th class="r">Accuracy</th><th class="r">n</th></tr></thead>
              <tbody>
                {#each Object.entries(result.per_person) as [k, v] (k)}<tr><td>{k}</td><td class="r num">{pct(v.accuracy)}</td><td class="r num">{v.n}</td></tr>{/each}
              </tbody>
            </table>
          {:else}
            <p class="muted small">Not available for this target and split (the evaluation reports per test group only).</p>
          {/if}
          <h3>Per test {result.config.split}</h3>
          <table>
            <thead><tr><th>{result.config.split}</th><th class="r">Model</th><th class="r">Baseline</th><th class="r">n</th></tr></thead>
            <tbody>
              {#each Object.entries(ev.scores.per_group) as [k, v] (k)}
                <tr><td class="mono">{k}</td><td class="r num">{pct(v.accuracy)}</td><td class="r num">{pct(ev.baseline.per_group[k]?.accuracy ?? 0)}</td><td class="r num">{v.n}</td></tr>
              {/each}
            </tbody>
          </table>
        </div>
      </div>
      <h3>Windows per session</h3>
      <table>
        <thead><tr><th>Session</th><th class="r">Events</th><th class="r">Skipped (lost samples)</th><th class="r">Kept</th><th class="r">Outside labels</th><th class="r">Silence</th><th class="r">No target</th><th>Classes</th></tr></thead>
        <tbody>
          {#each result.sessions as s (s.session)}
            <tr>
              <td class="mono">{s.session}{#if s.simulated} <span class="chip warn">sim</span>{/if}</td>
              <td class="r num">{s.events}</td><td class="r num">{s.windows_invalid}</td><td class="r num">{s.kept}</td>
              <td class="r num">{s.dropped.outside_labels}</td><td class="r num">{s.dropped.silence}</td><td class="r num">{s.dropped.no_target}</td>
              <td class="small">{Object.entries(s.classes).map(([k, v]) => `${k} ${v}`).join(', ')}</td>
            </tr>
          {/each}
        </tbody>
      </table>

      <h3>Draft EXP note</h3>
      {#if result.draft}<p class="small">Drafted: <span class="mono">{result.draft.path}</span></p>{/if}
      <div class="runrow">
        <input type="text" maxlength="60" bind:value={draftTitle} placeholder="short title" style="min-width:24em" />
        <button disabled={drafting || !draftTitle.trim()} onclick={makeDraft}>Draft EXP note</button>
        <span class="muted small">writes 50 Experiments/EXP-### &lt;title&gt;.md and checks it with vault_schema (any error deletes it)</span>
      </div>
      {#if draft}
        <div class="draft" class:bad={!draft.ok}>
          <p>{#if draft.ok}<b>{draft.path}</b> written.{:else}<b>Draft refused and deleted</b> ({draft.deleted}).{/if}</p>
          {#each draft.check.errors as e (e)}<p class="inline-err">{e}</p>{/each}
          <p class="small muted">vault_schema.py on the note (exit {draft.check.cli_rc ?? 'not run'}):</p>
          <pre>{draft.check.cli}</pre>
        </div>
      {/if}
    </section>
  {/if}

  <section class="card">
    <header><h2>Runs</h2><span class="muted small">{options?.runs_dir ?? 'tools/lab/runs'} (gitignored)</span><span class="grow"></span><button onclick={loadRuns}>Refresh</button></header>
    <div class="scroll">
      <table>
        <thead><tr><th>Run</th><th>Target</th><th>Model</th><th class="r">Sessions</th><th class="r">Balanced acc.</th><th class="r">Baseline</th><th class="r">Flags</th><th>EXP</th></tr></thead>
        <tbody>
          {#each runs as r (r.run_id)}
            <tr class="click" class:on={result?.run_id === r.run_id} onclick={() => open(r.run_id)}>
              <td class="mono">{r.run_id}{#if r.simulated} <span class="chip warn">sim</span>{/if}</td>
              <td>{r.target}</td><td>{r.model}</td><td class="r num">{r.sessions}</td>
              <td class="r num">{pct(r.balanced_accuracy)}</td><td class="r num">{pct(r.baseline_balanced_accuracy)}</td>
              <td class="r num">{r.flags}</td><td class="small">{r.draft?.id ?? ''}</td>
            </tr>
          {:else}
            <tr><td colspan="8" class="muted">No runs yet.</td></tr>
          {/each}
        </tbody>
      </table>
    </div>
  </section>
</div>

<style>
  .page { display: flex; flex-direction: column; gap: 12px; }
  h2 { font-size: 15px; margin: 0; }
  h3 { font-size: 13px; margin: 12px 0 6px; }
  table { border-collapse: collapse; width: 100%; font-size: 12.5px; }
  th, td { text-align: left; padding: 3px 8px; border-bottom: 1px solid var(--line); }
  .r { text-align: right; }
  .scroll { max-height: 320px; overflow: auto; margin-top: 8px; }
  .dim { opacity: 0.55; }
  .click { cursor: pointer; }
  .click:hover, .on { background: var(--panel2); }
  .groups { display: flex; flex-wrap: wrap; gap: 6px 14px; margin-top: 8px; align-items: center; }
  .runrow { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-top: 10px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }
  .heat td { min-width: 3em; }
  .flags { margin: 6px 0; padding-left: 0; list-style: none; font-size: 12.5px; }
  .simbanner { border: 1px solid var(--warn); color: var(--warn); border-radius: 6px; padding: 6px 10px; font-weight: 600; }
  .big { font-weight: 700; }
  .draft { border: 1px solid var(--line); border-radius: 6px; padding: 6px 10px; margin-top: 8px; }
  .draft.bad { border-color: var(--err); }
  pre { white-space: pre-wrap; font-size: 12px; margin: 4px 0; }
</style>
