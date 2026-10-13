<script lang="ts">
  // Datasets page (WEB_API.md section 13): every session (repo sidecars + WAVs on the data root), filters,
  // totals, and the data/manifest.json builder (preview first, then build).
  import { onMount } from 'svelte';
  import { app } from '../lib/store.svelte';
  import { ApiError, isAbort } from '../lib/api';
  import {
    datasetsApi,
    type DatasetFilters,
    type DatasetList,
    type DatasetRow,
    type ManifestPlan,
    type ManifestRequest,
    type ManifestResult,
  } from '../lib/datasets';
  import { fmtFixed, fmtInt } from '../lib/format';

  let { onOpenReview }: { onOpenReview: (session: string) => void } = $props();

  type Tri = '' | 'true' | 'false';
  type SortKey = 'session' | 'date' | 'floor' | 'protocol' | 'people' | 'duration_s' | 'label_count' | 'valid' | 'wav';

  let protocol = $state('');
  let floor = $state('');
  let person = $state('');
  let valid = $state<Tri>('');
  let wav = $state<'' | 'present' | 'missing'>('');
  let simulated = $state<Tri>('');
  let dateFrom = $state('');
  let dateTo = $state('');

  let data = $state.raw<DatasetList | null>(null);
  let loadError = $state<string | null>(null);
  let loading = $state(false);
  let rebuilding = $state(false);
  let sortKey = $state<SortKey>('session');
  let sortAsc = $state(false);
  let selected = $state.raw<Set<string>>(new Set());
  let expanded = $state<string | null>(null);

  let builderOpen = $state(false);
  let useSelection = $state(false);
  let includeSim = $state(false);
  let includeInvalid = $state(false);
  let plan = $state.raw<ManifestPlan | null>(null);
  let result = $state.raw<ManifestResult | null>(null);
  let planning = $state(false);
  let building = $state(false);

  const tri = (v: Tri): boolean | undefined => (v === '' ? undefined : v === 'true');

  const filters = $derived<DatasetFilters>({
    protocol: protocol || undefined,
    floor: floor || undefined,
    person: person || undefined,
    valid: tri(valid),
    wav: wav || undefined,
    simulated: tri(simulated),
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
  });

  const rows = $derived.by(() => {
    const list = [...(data?.sessions ?? [])];
    const key = (r: DatasetRow): string | number => {
      switch (sortKey) {
        case 'people':
          return r.people.join(',');
        case 'duration_s':
          return r.duration_s ?? -1;
        case 'valid':
          return r.valid ? 1 : 0;
        case 'wav':
          return r.wav_present ? 1 : 0;
        default:
          return r[sortKey] ?? '';
      }
    };
    list.sort((a, b) => {
      const x = key(a);
      const y = key(b);
      const c = x < y ? -1 : x > y ? 1 : a.session < b.session ? -1 : 1;
      return sortAsc ? c : -c;
    });
    return list;
  });

  let ctrl: AbortController | null = null;
  async function load(): Promise<void> {
    ctrl?.abort();
    const mine = new AbortController();
    ctrl = mine;
    loading = true;
    try {
      data = await datasetsApi.list(filters, mine.signal);
      loadError = null;
      const shown = new Set(data.sessions.map((s) => s.session));
      selected = new Set([...selected].filter((n) => shown.has(n)));
    } catch (e) {
      if (!isAbort(e)) loadError = e instanceof ApiError ? e.message : String(e);
    } finally {
      if (ctrl === mine) loading = false;
    }
  }

  $effect(() => {
    void filters;
    void load();
  });

  function clearFilters(): void {
    protocol = floor = person = dateFrom = dateTo = '';
    valid = simulated = '';
    wav = '';
  }

  async function rebuild(): Promise<void> {
    rebuilding = true;
    try {
      const r = await datasetsApi.rebuild();
      app.toast(`Index rebuilt from ${r.refresh.sidecars} sidecars in ${r.refresh.seconds.toFixed(1)} s.`, 'info');
      await load();
    } catch (e) {
      app.toast(e instanceof ApiError ? e.message : String(e), 'error');
    } finally {
      rebuilding = false;
    }
  }

  function sortBy(k: SortKey): void {
    if (sortKey === k) sortAsc = !sortAsc;
    else {
      sortKey = k;
      sortAsc = k !== 'session' && k !== 'date';
    }
  }

  function toggle(name: string): void {
    const s = new Set(selected);
    if (s.has(name)) s.delete(name);
    else s.add(name);
    selected = s;
  }

  function toggleAll(): void {
    selected = selected.size === rows.length ? new Set() : new Set(rows.map((r) => r.session));
  }

  async function hashOne(name: string): Promise<void> {
    try {
      await datasetsApi.hash(name);
      await load();
    } catch (e) {
      app.toast(e instanceof ApiError ? e.message : String(e), 'error');
    }
  }

  function manifestRequest(): ManifestRequest {
    return useSelection
      ? { sessions: [...selected], include_simulated: includeSim, include_invalid: includeInvalid }
      : { filters, include_simulated: includeSim, include_invalid: includeInvalid };
  }

  async function preview(): Promise<void> {
    planning = true;
    result = null;
    try {
      plan = await datasetsApi.preview(manifestRequest());
    } catch (e) {
      plan = null;
      app.toast(e instanceof ApiError ? e.message : String(e), 'error');
    } finally {
      planning = false;
    }
  }

  async function build(): Promise<void> {
    if (!plan) return;
    if (plan.exists && !confirm(`${plan.out} exists. Replace it with ${plan.sessions.length} sessions?`)) return;
    building = true;
    try {
      result = await datasetsApi.build(manifestRequest());
      plan = null;
      app.toast(`Wrote ${result.written}: ${result.entries} recordings.`, 'info');
      await load();
    } catch (e) {
      app.toast(e instanceof ApiError ? e.message : String(e), 'error');
    } finally {
      building = false;
    }
  }

  function openBuilder(): void {
    builderOpen = true;
    useSelection = selected.size > 0;
    plan = null;
    result = null;
  }

  $effect(() => {
    // a changed selection, filter or option makes an open preview stale
    void [useSelection, includeSim, includeInvalid, selected, filters];
    plan = null;
  });

  const fmtH = (s: number | null): string => (s === null ? '—' : s >= 3600 ? `${(s / 3600).toFixed(2)} h` : s >= 60 ? `${(s / 60).toFixed(1)} min` : `${s.toFixed(1)} s`);
  const fmtMB = (b: number): string => `${(b / 1e6).toFixed(b >= 1e8 ? 0 : 1)} MB`;
  const lossText = (r: DatasetRow): string => (r.loss ? `${r.loss.device} / ${r.loss.link} / ${r.loss.host}` : '—');
  const arrow = (k: SortKey): string => (sortKey === k ? (sortAsc ? ' ▲' : ' ▼') : '');

  onMount(() => () => ctrl?.abort());
</script>

{#snippet th(k: SortKey, label: string, cls = '')}
  <th class={cls} aria-sort={sortKey === k ? (sortAsc ? 'ascending' : 'descending') : 'none'}>
    <button class="sort" onclick={() => sortBy(k)}>{label}{arrow(k)}</button>
  </th>
{/snippet}

<div class="datasets">
  <div class="toolbar filters" role="search" aria-label="Session filters">
    <label>Protocol
      <select bind:value={protocol}>
        <option value="">any</option>
        {#each data?.facets.protocols ?? [] as p (p)}<option value={p}>{p}</option>{/each}
      </select>
    </label>
    <label>Floor
      <select bind:value={floor}>
        <option value="">any</option>
        {#each data?.facets.floors ?? [] as f (f)}<option value={f}>{f}</option>{/each}
      </select>
    </label>
    <label>Person
      <select bind:value={person}>
        <option value="">any</option>
        {#each data?.facets.people ?? [] as p (p)}<option value={p}>{p}</option>{/each}
      </select>
    </label>
    <label>Valid
      <select bind:value={valid}><option value="">any</option><option value="true">valid</option><option value="false">invalid</option></select>
    </label>
    <label>WAV
      <select bind:value={wav}><option value="">any</option><option value="present">present</option><option value="missing">missing</option></select>
    </label>
    <label>Simulated
      <select bind:value={simulated}><option value="">any</option><option value="false">real</option><option value="true">simulated</option></select>
    </label>
    <label>From <input type="date" bind:value={dateFrom} /></label>
    <label>To <input type="date" bind:value={dateTo} /></label>
    <button onclick={clearFilters}>Clear</button>
    <span class="grow"></span>
    <button onclick={() => void rebuild()} disabled={rebuilding} title="Drop the local cache and read every sidecar again">
      {rebuilding ? 'Rebuilding…' : 'Rebuild index'}
    </button>
    <button class="primary" onclick={openBuilder}>Build manifest…</button>
  </div>

  {#if loadError}
    <div class="inline-err" role="alert">{loadError} <button onclick={() => void load()}>Retry</button></div>
  {/if}
  {#if data && !data.index.data_root.ok}
    <div class="inline-err" role="status">
      {data.index.data_root.error?.message ?? 'No usable data root.'} Every WAV shows as missing until it is set (Record page).
    </div>
  {/if}

  {#if data}
    <section class="totals" aria-label="Totals of the shown sessions">
      <div class="card stat"><span class="k">Sessions</span><span class="num v">{data.totals.sessions}</span><small class="muted">of {data.all}</small></div>
      <div class="card stat"><span class="k">Hours</span><span class="num v">{fmtFixed(data.totals.hours, 2)}</span></div>
      <div class="card stat"><span class="k">Labels</span><span class="num v">{fmtInt(data.totals.labels)}</span></div>
      <div class="card stat"><span class="k">Problems</span>
        <span class="small">
          <span class="chip err">{data.totals.invalid} invalid</span>
          <span class="chip warn">{data.totals.wav_missing} WAV missing</span>
          <span class="chip">{data.totals.simulated} simulated</span>
        </span>
      </div>
      <div class="card stat people"><span class="k">Per person</span>
        <span class="small">
          {#each data.totals.per_person as p (p.person)}
            <span class="chip" title="{p.sessions} sessions"><b class="mono">{p.person}</b> {p.sessions} · {fmtFixed(p.hours, 2)} h</span>
          {:else}<span class="muted">none</span>{/each}
        </span>
      </div>
    </section>
  {/if}

  {#if builderOpen}
    <section class="card builder" aria-label="Build manifest">
      <header>
        <h2>Build manifest</h2>
        <span class="muted small">Writes {data?.index.manifest.path ?? 'data/manifest.json'} with a SHA-256 of every listed WAV (the WAVs are read in full).</span>
        <span class="grow"></span>
        <button onclick={() => (builderOpen = false)} aria-label="Close the manifest builder">Close</button>
      </header>
      <div class="row">
        <div class="seg" role="group" aria-label="Which sessions">
          <button class:on={!useSelection} onclick={() => (useSelection = false)}>The filtered list ({rows.length})</button>
          <button class:on={useSelection} disabled={selected.size === 0} onclick={() => (useSelection = true)}>Selected ({selected.size})</button>
        </div>
        <label class="check"><input type="checkbox" bind:checked={includeSim} /> include simulated</label>
        <label class="check"><input type="checkbox" bind:checked={includeInvalid} /> include invalid</label>
        <button onclick={() => void preview()} disabled={planning}>{planning ? 'Checking…' : 'Preview'}</button>
        <button class="primary" onclick={() => void build()} disabled={!plan || plan.sessions.length === 0 || building}>
          {building ? 'Hashing and writing…' : 'Build'}
        </button>
      </div>
      {#if plan}
        <div class="plan">
          <p>
            <b>{plan.sessions.length}</b> sessions, {plan.entries} recordings, {fmtFixed(plan.hours, 2)} h; {fmtMB(plan.bytes_to_hash)} to hash.
            {#if plan.wav_missing}<span class="chip warn">{plan.wav_missing} WAV missing (listed without a hash)</span>{/if}
            {#if plan.exists}<span class="chip warn">replaces {plan.out}</span>{/if}
          </p>
          {#if plan.excluded.length}
            <details open={plan.excluded.length <= 8}>
              <summary>{plan.excluded.length} left out</summary>
              <ul class="excl">
                {#each plan.excluded as x (x.session + (x.wav ?? ''))}<li><span class="mono">{x.session}</span>: {x.reason}</li>{/each}
              </ul>
            </details>
          {:else}
            <p class="muted small">Nothing is left out.</p>
          {/if}
        </div>
      {/if}
      {#if result}
        <div class="plan ok" role="status">
          <p>
            Wrote <b class="mono">{result.written}</b>: {result.entries} recordings from {result.sessions.length} sessions,
            {fmtFixed(result.hours, 2)} h, {fmtMB(result.bytes_hashed)} hashed in {result.seconds.toFixed(1)} s.
          </p>
          {#if result.excluded.length}
            <details><summary>{result.excluded.length} left out</summary>
              <ul class="excl">{#each result.excluded as x (x.session + (x.wav ?? ''))}<li><span class="mono">{x.session}</span>: {x.reason}</li>{/each}</ul>
            </details>
          {/if}
          {#if result.unmatched_wavs.length}
            <p class="small muted">{result.unmatched_wavs.length} WAVs in these sessions have no sidecar in the repository (listed under unmatched_wavs).</p>
          {/if}
          <p class="small muted">Commit it with the sidecars when a result uses it (a person decides).</p>
        </div>
      {/if}
    </section>
  {/if}

  <section class="card tablecard">
    <header>
      <h2>Sessions</h2>
      {#if loading}<span class="muted small">loading…</span>{/if}
      <span class="grow"></span>
      {#if data?.index.refresh}
        <span class="muted small">
          index: {data.index.refresh.sidecars} sidecars, {data.index.refresh.sessions_rebuilt} sessions re-read
        </span>
      {/if}
    </header>
    {#if data && data.sessions.length === 0}
      <p class="muted">{data.all === 0 ? 'No session yet: the repository has no sidecar under data/ and the data root no session folder.' : 'No session matches the filters.'}</p>
    {:else if data}
      <div class="scroll">
        <table>
          <thead>
            <tr>
              <th><input type="checkbox" aria-label="Select all shown" checked={selected.size > 0 && selected.size === rows.length} onchange={toggleAll} /></th>
              {@render th('session', 'Session')}
              {@render th('date', 'Date')}
              <th>Site / room</th>
              {@render th('floor', 'Floor')}
              {@render th('people', 'People')}
              {@render th('duration_s', 'Duration', 'r')}
              {@render th('label_count', 'Labels', 'r')}
              {@render th('protocol', 'Protocol')}
              <th class="r" title="Lost samples: device / link / host">Loss</th>
              {@render th('valid', 'State')}
              <th></th>
            </tr>
          </thead>
          <tbody>
            {#each rows as r (r.session)}
              <tr class:sel={selected.has(r.session)}>
                <td><input type="checkbox" aria-label="Select {r.session}" checked={selected.has(r.session)} onchange={() => toggle(r.session)} /></td>
                <td><button class="link mono" onclick={() => (expanded = expanded === r.session ? null : r.session)} aria-expanded={expanded === r.session}>{r.session}</button></td>
                <td class="mono">{r.date}</td>
                <td>{r.site} / {r.room}</td>
                <td>{r.floor ?? '—'}</td>
                <td class="mono">{r.people.join(', ') || '—'}</td>
                <td class="r num">{fmtH(r.duration_s)}</td>
                <td class="r num">{r.label_count}</td>
                <td class="mono small">{r.protocol ?? '—'}</td>
                <td class="r num small" class:lossbad={!!r.loss && r.loss.device + r.loss.link + r.loss.host > 0}>{lossText(r)}</td>
                <td class="badges">
                  {#if r.valid}<span class="chip ok">valid</span>{:else}<span class="chip err" title={r.errors.join('\n')}>invalid</span>{/if}
                  {#if !r.wav_present}<span class="chip warn">WAV missing</span>{/if}
                  {#if r.simulated}<span class="chip">simulated</span>{/if}
                  {#if r.incomplete}<span class="chip warn">incomplete</span>{/if}
                  {#if r.sidecar_source === 'data_root'}<span class="chip" title="Sidecars read from the data root, next to the WAVs; import or copy them to data/ before a manifest can list this session">not in repo</span>{:else if !r.sidecar_source}<span class="chip warn">no sidecar</span>{/if}
                </td>
                <td>
                  <button onclick={() => onOpenReview(r.session)} disabled={!r.on_data_root} title={r.on_data_root ? 'Open this session on the Review page' : 'Not on the data root'}>Open in Review</button>
                </td>
              </tr>
              {#if expanded === r.session}
                <tr class="detail">
                  <td></td>
                  <td colspan="11">
                    {#if r.errors.length}
                      <ul class="errs">{#each r.errors as e, i (i)}<li>{e}</li>{/each}</ul>
                    {/if}
                    {#if r.warnings.length}
                      <ul class="warns">{#each r.warnings as w, i (i)}<li>{w}</li>{/each}</ul>
                    {/if}
                    {#if r.sidecar_source === 'data_root'}
                      <p class="small muted">Not in the repository: these sidecars were read and validated from the data root, next to the WAVs. A manifest lists the session only after its sidecars are imported or copied to data/.</p>
                    {/if}
                    <table class="streams">
                      <thead><tr><th>Stream</th><th>WAV</th><th class="r">Frames</th><th class="r">Rate (Hz)</th><th class="r">Size</th><th>Surface</th><th>SHA-256</th></tr></thead>
                      <tbody>
                        {#each r.streams as s (s.wav)}
                          <tr>
                            <td class="mono">{s.stream ?? 'v0'}</td>
                            <td class="mono small">{s.wav}{#if !s.wav_present}<span class="chip warn">missing</span>{/if}</td>
                            <td class="r num">{fmtInt(s.frames)}</td>
                            <td class="r num">{s.fs_measured_hz !== null ? fmtFixed(s.fs_measured_hz, 2) : (s.fs_header_hz ?? '—')}</td>
                            <td class="r num">{s.size_bytes !== null ? fmtMB(s.size_bytes) : '—'}</td>
                            <td class="small">{s.surface.join(', ') || '—'}</td>
                            <td class="mono small">{s.sha256 ? s.sha256.slice(0, 16) + '…' : '—'}</td>
                          </tr>
                        {/each}
                      </tbody>
                    </table>
                    {#if r.streams.some((s) => s.wav_present && !s.sha256)}
                      <button onclick={() => void hashOne(r.session)}>Compute SHA-256</button>
                    {/if}
                  </td>
                </tr>
              {/if}
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </section>
</div>

<style>
  .datasets {
    display: flex;
    flex-direction: column;
    gap: 10px;
    min-width: 0;
  }
  .filters .grow {
    flex: 1;
  }
  .filters input[type='date'] {
    width: 140px;
  }
  .totals {
    display: grid;
    grid-template-columns: repeat(3, minmax(90px, 140px)) minmax(180px, 1fr) minmax(200px, 2fr);
    gap: 10px;
  }
  .stat {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .stat .k {
    font-size: 12px;
    color: var(--muted);
  }
  .stat .v {
    font-size: 22px;
    font-weight: 600;
  }
  .stat .small {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }
  .scroll {
    overflow-x: auto;
  }
  th .sort {
    background: none;
    border: none;
    padding: 0;
    color: var(--muted);
    font-size: 12px;
  }
  tr.sel td {
    background: var(--panel2);
  }
  .badges {
    white-space: nowrap;
  }
  .badges .chip + .chip {
    margin-left: 4px;
  }
  button.link {
    background: none;
    border: none;
    padding: 0;
    color: var(--accent);
    text-align: left;
  }
  .detail > td {
    padding: 6px 0 10px;
  }
  .errs,
  .warns,
  .excl {
    margin: 0 0 6px;
    padding-left: 18px;
  }
  .errs {
    color: var(--err);
  }
  .warns {
    color: var(--warn);
  }
  table.streams {
    margin-bottom: 6px;
  }
  .builder .row {
    align-items: center;
  }
  .check {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .plan {
    margin-top: 8px;
    padding: 8px 10px;
    border: 1px solid var(--line);
    border-radius: 6px;
    background: var(--panel2);
  }
  .plan p {
    margin: 0 0 4px;
  }
  .plan.ok {
    border-color: var(--ok);
  }
  .small {
    font-size: 12px;
  }
  @media (max-width: 900px) {
    .totals {
      grid-template-columns: repeat(3, 1fr);
    }
    .totals .people {
      grid-column: 1 / -1;
    }
  }
</style>
