<script lang="ts">
  // Pack bench (Lab phase 5, WEB_API.md "Pack bench"). Every number comes from the server, which calls rezonating_ml.
  import type uPlot from 'uplot';
  import { onMount } from 'svelte';
  import Plot from './Plot.svelte';
  import { request } from '../lib/api';
  import { axisBase, cssVar, readPalette } from '../lib/plotopts';
  import { app } from '../lib/store.svelte';

  interface PackInfo { id: string; name?: string; trigger?: Record<string, unknown> | null; tunable?: boolean }
  interface Env { k: number[]; min: (number | null)[]; max: (number | null)[] }
  interface Ev { onset: number; start: number; end: number; n_invalid?: number; input_index?: number }
  interface Score {
    tolerance_ms: number; n_truth: number; n_events: number; true_positives: number; false_positives: number;
    false_negatives: number; precision: number | null; recall: number | null;
    onset_error_ms: Record<string, number | null>;
  }
  interface View {
    empty?: boolean; message?: string; pack: string; fs_hz: number; n: number; threshold: number | null;
    stage_order: string[]; stages: Record<string, { status: string; detail: string }>;
    filtered: Env | null; ratio: Env | null; events: Ev[]; windows: Ev[]; counts: Record<string, number>;
    feature_names: string[]; features: { onset: number; values: number[] }[] | null;
    model: { classes: string[]; rows: { onset: number; label: string; proba: number[] }[] } | null;
    model_info: Record<string, unknown> | null; score: Score | null; n_invalid_out: number;
    source: Record<string, unknown>;
  }
  interface Compare {
    n_fw: number; n_py: number; matched: number; missing: number; extra: number; missing_idx: number[];
    extra_idx: number[]; diffs: { fw: number; py: number; diff: number }[]; range: number[]; note: string;
    starts_at_acquisition_start: boolean;
  }

  const TUNE: { key: string; label: string; min: number; max: number; step: number }[] = [
    { key: 'sta_ms', label: 'STA (ms)', min: 5, max: 500, step: 5 },
    { key: 'lta_ms', label: 'LTA (ms)', min: 200, max: 10000, step: 100 },
    { key: 'ratio', label: 'ratio', min: 1.1, max: 20, step: 0.1 },
    { key: 'pre_ms', label: 'pre (ms)', min: 0, max: 1000, step: 10 },
    { key: 'post_ms', label: 'post (ms)', min: 10, max: 3000, step: 10 },
  ];
  const VECTOR_WARNING = "changing footstep-id's trigger invalidates ml/tests/vectors: regenerate them and tell firmware";

  let packs: PackInfo[] = $state([]);
  let packId = $state('footstep-id');
  let kind = $state<'recording' | 'sim' | 'live'>('sim');
  let root = $state('');
  let sessions: { name: string; truth: boolean }[] = $state([]);
  let session = $state('');
  let trainSel: string[] = $state([]);
  let channel = $state(0);
  let trig: Record<string, number> = $state({});
  let view: View | null = $state(null);
  let busy = $state(false);
  let diff: { diff: string; warnings: string[]; changed: boolean } | null = $state(null);
  let cmp: Compare | null = $state(null);
  let clip = $state({ k0: 0, k1: 6000, folder: '', filename: 'sta_lta_clip.json' });
  let checkPath = $state('');
  let vecMsg = $state('');
  let fplot: ReturnType<typeof Plot> | undefined = $state();
  let rplot: ReturnType<typeof Plot> | undefined = $state();

  const pack = $derived(packs.find((p) => p.id === packId));
  const src = $derived({ kind, session: kind === 'live' ? null : session, root: root || null, channel });

  function err(e: unknown): void {
    app.toast(e instanceof Error ? e.message : String(e));
  }

  function resetTrigger(): void {
    const t = (pack?.trigger ?? {}) as Record<string, unknown>;
    trig = Object.fromEntries(TUNE.filter((d) => typeof t[d.key] === 'number').map((d) => [d.key, t[d.key] as number]));
  }

  async function loadPacks(): Promise<void> {
    try {
      packs = (await request<{ packs: PackInfo[] }>('GET', '/api/bench/packs')).packs;
      resetTrigger();
    } catch (e) {
      err(e);
    }
  }

  async function loadSessions(): Promise<void> {
    try {
      const q = root ? `?root=${encodeURIComponent(root)}` : '';
      sessions = (await request<{ sessions: { name: string; truth: boolean }[] }>('GET', `/api/bench/sessions${q}`)).sessions;
      if (!sessions.some((s) => s.name === session)) session = sessions[0]?.name ?? '';
    } catch (e) {
      sessions = [];
      err(e);
    }
  }

  async function run(): Promise<void> {
    if (kind !== 'live' && !session) return;
    busy = true;
    try {
      view = await request<View>('POST', '/api/bench/run', { pack: packId, source: src, trigger: pack?.tunable ? trig : null });
    } catch (e) {
      err(e);
    } finally {
      busy = false;
    }
  }

  async function train(): Promise<void> {
    busy = true;
    try {
      const sources = (trainSel.length ? trainSel : [session]).map((s) => ({ kind, session: s, root: root || null, channel }));
      await request('POST', '/api/bench/train', { pack: packId, sources, trigger: pack?.tunable ? trig : null });
      await run();
    } catch (e) {
      err(e);
    } finally {
      busy = false;
    }
  }

  async function forget(): Promise<void> {
    await request('DELETE', '/api/bench/model').catch(err);
    await run();
  }

  async function preview(): Promise<void> {
    try {
      diff = await request('POST', '/api/bench/trigger/preview', { pack: packId, trigger: trig });
    } catch (e) {
      err(e);
    }
  }

  async function save(): Promise<void> {
    try {
      await request('POST', '/api/bench/trigger/save', { pack: packId, trigger: trig });
      app.toast('pack.json saved and validated', 'info');
      diff = null;
      await loadPacks();
    } catch (e) {
      err(e);
    }
  }

  async function compare(): Promise<void> {
    try {
      cmp = await request<Compare>('POST', '/api/bench/compare', { pack: packId, channel });
    } catch (e) {
      err(e);
    }
  }

  async function makeVector(): Promise<void> {
    try {
      const r = await request<{ path: string; events: number; warning: string | null }>('POST', '/api/bench/vector/create', {
        pack: packId, source: src, trigger: pack?.tunable ? trig : null, k0: clip.k0, k1: clip.k1,
        folder: clip.folder || null, filename: clip.filename,
      });
      checkPath = r.path;
      vecMsg = `wrote ${r.path} (${r.events} events)${r.warning ? ' - ' + r.warning : ''}`;
    } catch (e) {
      err(e);
    }
  }

  async function checkVector(): Promise<void> {
    try {
      const r = await request<{ ok: boolean; problems: string[] }>('POST', '/api/bench/vector/check', { path: checkPath });
      vecMsg = r.ok ? `${checkPath}: passes the current pipeline` : r.problems.join('; ');
    } catch (e) {
      err(e);
    }
  }

  function series(env: Env | null, fs: number): number[][] {
    if (!env) return [[], [], []];
    return [env.k.map((k) => k / fs), env.min.map((v) => v ?? NaN), env.max.map((v) => v ?? NaN)];
  }

  const pal = readPalette();
  const accent = cssVar('--accent', '#60a5fa');
  const fopts: Omit<uPlot.Options, 'width' | 'height'> = {
    scales: { x: { time: false } },
    legend: { show: false },
    series: [{}, { stroke: accent, width: 1 }, { stroke: accent, width: 1 }],
    axes: [{ ...axisBase(pal, 's') }, { ...axisBase(pal, 'filtered', 'codes'), size: 64 }],
  };
  const ropts: Omit<uPlot.Options, 'width' | 'height'> = {
    scales: { x: { time: false } },
    legend: { show: false },
    series: [{}, { stroke: accent, width: 1 }, { stroke: pal.err, width: 1, dash: [6, 4] }],
    axes: [{ ...axisBase(pal, 's') }, { ...axisBase(pal, 'STA/LTA'), size: 64 }],
  };

  $effect(() => {
    const v = view;
    if (!v || v.empty) return;
    const [x, lo, hi] = series(v.filtered, v.fs_hz);
    fplot?.setData([x, lo, hi] as unknown as uPlot.AlignedData, true);
    const [rx, , rmax] = series(v.ratio, v.fs_hz);
    rplot?.setData([rx, rmax, rx.map(() => v.threshold ?? NaN)] as unknown as uPlot.AlignedData, true);
  });

  function st(name: string): string {
    return view && !view.empty ? (view.stages[name]?.status ?? 'not_available') : 'not_available';
  }
  function fmt(v: number | null | undefined, d = 3): string {
    return v === null || v === undefined ? '-' : Number(v).toFixed(d);
  }

  onMount(() => {
    void loadPacks().then(loadSessions);
  });
</script>

<section class="bench">
  <header class="bar">
    <label>Pack
      <select bind:value={packId} onchange={resetTrigger}>
        {#each packs as p (p.id)}<option value={p.id}>{p.id}</option>{/each}
      </select>
    </label>
    <label>Source
      <select bind:value={kind}>
        <option value="sim">simulator (sim-dataset)</option>
        <option value="recording">recording</option>
        <option value="live">live node / live sim</option>
      </select>
    </label>
    {#if kind !== 'live'}
      <label>Folder <input placeholder="data root" bind:value={root} onchange={loadSessions} size="28" /></label>
      <label>Session
        <select bind:value={session}>
          {#each sessions as s (s.name)}<option value={s.name}>{s.name}{s.truth ? ' (truth)' : ''}</option>{/each}
        </select>
      </label>
    {/if}
    <label>Channel <input type="number" min="0" max="3" bind:value={channel} style="width:4em" /></label>
    <button onclick={run} disabled={busy}>{busy ? 'Running...' : 'Run'}</button>
  </header>

  {#if view?.empty}<p class="muted">{view.message}</p>{/if}

  {#if pack?.tunable}
    <div class="panel">
      <h3>Trigger tuning</h3>
      <div class="sliders">
        {#each TUNE as d (d.key)}
          {#if trig[d.key] !== undefined}
            <label>{d.label} <b>{trig[d.key]}</b>
              <input type="range" min={d.min} max={d.max} step={d.step} bind:value={trig[d.key]} onchange={run} />
            </label>
          {/if}
        {/each}
      </div>
      <button onclick={resetTrigger}>Reset to pack.json</button>
      <button onclick={preview}>Save to pack.json...</button>
      {#if packId === 'footstep-id'}<p class="warn">{VECTOR_WARNING}</p>{/if}
      {#if diff}
        <pre class="diff">{diff.changed ? diff.diff : 'No change.'}</pre>
        {#each diff.warnings as w (w)}<p class="warn">{w}</p>{/each}
        <button onclick={save} disabled={!diff.changed}>Write trigger block and validate</button>
        <button onclick={() => (diff = null)}>Cancel</button>
      {/if}
    </div>
  {/if}

  {#if view && !view.empty}
    {#each view.stage_order as name (name)}
      <div class="stage" class:off={st(name) === 'not_available'}>
        <span class="tag">{name}</span> <span class="status">{st(name)}</span>
        <span class="muted">{view.stages[name]?.detail}</span>
      </div>
    {/each}

    <div class="panel" class:off={st('dsp') === 'not_available'}>
      <h3>Filtered signal <small class="muted">{view.n} samples at {view.fs_hz} Hz, {view.n_invalid_out} invalid</small></h3>
      <Plot bind:this={fplot} options={fopts} height={170} />
    </div>
    <div class="panel" class:off={st('trigger') === 'not_available'}>
      <h3>STA/LTA ratio <small class="muted">threshold {view.threshold ?? '-'}</small></h3>
      <Plot bind:this={rplot} options={ropts} height={150} />
    </div>
    <div class="panel" class:off={st('trigger') === 'not_available'}>
      <h3>Events and windows <small class="muted">{view.counts.events} events, {view.counts.windows} windows,
        {view.counts.windows_invalid} with n_invalid &gt; 0 ({view.counts.windows_cut} cut)</small></h3>
      <div class="scroll"><table>
        <thead><tr><th>onset</th><th>start</th><th>end</th><th>n_invalid</th></tr></thead>
        <tbody>{#each view.windows.slice(0, 300) as w (w.onset)}<tr><td>{w.onset}</td><td>{w.start}</td><td>{w.end}</td><td class:bad={!!w.n_invalid}>{w.n_invalid}</td></tr>{/each}</tbody>
      </table></div>
    </div>
    <div class="panel" class:off={st('features') === 'not_available'}>
      <h3>Features <small class="muted">13 per window with n_invalid = 0</small></h3>
      {#if view.features}
        <div class="scroll"><table>
          <thead><tr><th>onset</th>{#each view.feature_names as f (f)}<th>{f}</th>{/each}</tr></thead>
          <tbody>{#each view.features.slice(0, 200) as r (r.onset)}<tr><td>{r.onset}</td>{#each r.values as v, i (i)}<td>{v.toPrecision(4)}</td>{/each}</tr>{/each}</tbody>
        </table></div>
      {:else}<p class="muted">not available</p>{/if}
    </div>
    <div class="panel" class:off={st('model') === 'not_available'}>
      <h3>Model output</h3>
      {#if view.model}
        <p class="muted">{String(view.model_info?.kind ?? '')}: {String(view.model_info?.note ?? '')}</p>
        <div class="scroll"><table>
          <thead><tr><th>onset</th><th>label</th>{#each view.model.classes as c (c)}<th>p({c})</th>{/each}</tr></thead>
          <tbody>{#each view.model.rows.slice(0, 200) as r (r.onset)}<tr><td>{r.onset}</td><td>{r.label}</td>{#each r.proba as p, i (i)}<td>{p.toFixed(3)}</td>{/each}</tr>{/each}</tbody>
        </table></div>
        <button onclick={forget}>Forget model</button>
      {:else}
        <p class="muted">not available: {view.stages.model?.detail}</p>
      {/if}
      {#if kind !== 'live'}
        <label>Train on <select multiple bind:value={trainSel} size="3">
          {#each sessions as s (s.name)}<option value={s.name}>{s.name}</option>{/each}
        </select></label>
        <button onclick={train} disabled={busy}>Train a baseline on the selected sessions' labels</button>
      {/if}
    </div>

    {#if view.score}
      <div class="panel">
        <h3>Score against ground truth <small class="muted">match within ±{view.score.tolerance_ms} ms</small></h3>
        <table class="kv"><tbody>
          <tr><th>truth steps</th><td>{view.score.n_truth}</td><th>events</th><td>{view.score.n_events}</td></tr>
          <tr><th>true pos.</th><td>{view.score.true_positives}</td><th>false pos.</th><td>{view.score.false_positives}</td></tr>
          <tr><th>false neg.</th><td>{view.score.false_negatives}</td><th></th><td></td></tr>
          <tr><th>precision</th><td>{fmt(view.score.precision)}</td><th>recall</th><td>{fmt(view.score.recall)}</td></tr>
          <tr><th>onset error mean (ms)</th><td>{fmt(view.score.onset_error_ms.mean, 1)}</td><th>median / |p95|</th>
            <td>{fmt(view.score.onset_error_ms.median, 1)} / {fmt(view.score.onset_error_ms.abs_p95, 1)}</td></tr>
        </tbody></table>
      </div>
    {/if}
  {/if}

  <div class="panel">
    <h3>Compare: node EVENT frames vs Python <small class="muted">live source, pack as saved</small></h3>
    <button onclick={compare}>Compare now</button>
    {#if cmp}
      <table class="kv"><tbody>
        <tr><th>node events</th><td>{cmp.n_fw}</td><th>Python events</th><td>{cmp.n_py}</td></tr>
        <tr><th>matched</th><td>{cmp.matched}</td><th>missing / extra</th><td class:bad={cmp.missing + cmp.extra > 0}>{cmp.missing} / {cmp.extra}</td></tr>
        <tr><th>adc_dec range</th><td colspan="3">{cmp.range[0]} - {cmp.range[1]}{cmp.starts_at_acquisition_start ? '' : ' (ring does not reach the acquisition start)'}</td></tr>
      </tbody></table>
      {#if cmp.diffs.length}
        <table><thead><tr><th>node</th><th>Python</th><th>diff</th></tr></thead>
          <tbody>{#each cmp.diffs.slice(0, 100) as d (d.fw)}<tr><td>{d.fw}</td><td>{d.py}</td><td>{d.diff}</td></tr>{/each}</tbody></table>
      {/if}
      <p class="muted">{cmp.note}</p>
    {/if}
  </div>

  <div class="panel">
    <h3>Test vectors <small class="muted">sta_lta.json format; ml/tests/vectors is generated by rezonating_ml.vectors</small></h3>
    <label>k0 <input type="number" bind:value={clip.k0} style="width:7em" /></label>
    <label>k1 <input type="number" bind:value={clip.k1} style="width:7em" /></label>
    <label>Folder <input placeholder="data root/bench-vectors" bind:value={clip.folder} /></label>
    <label>File <input bind:value={clip.filename} /></label>
    <button onclick={makeVector} disabled={kind === 'live'}>Create test vector from clip</button>
    <br />
    <label>Vector file <input bind:value={checkPath} size="50" /></label>
    <button onclick={checkVector} disabled={!checkPath}>Check</button>
    {#if vecMsg}<p class="muted">{vecMsg}</p>{/if}
  </div>
</section>

<style>
  .bench { display: flex; flex-direction: column; gap: 12px; }
  .bar, .sliders { display: flex; flex-wrap: wrap; gap: 12px; align-items: end; }
  .sliders label { display: flex; flex-direction: column; min-width: 160px; }
  .panel { background: var(--panel); border: 1px solid var(--border, #334); border-radius: 8px; padding: 10px 12px; }
  .panel h3 { margin: 0 0 8px; font-size: 14px; }
  .off { opacity: 0.45; filter: grayscale(1); }
  .stage { display: flex; gap: 10px; font-size: 13px; }
  .tag { font-weight: 600; min-width: 80px; }
  .status { font-family: ui-monospace, monospace; min-width: 110px; }
  .muted { color: var(--muted, #8593a3); font-weight: normal; }
  .warn { color: var(--warn, #f59e0b); }
  .bad { color: var(--err, #f87171); }
  .scroll { max-height: 260px; overflow: auto; }
  table { border-collapse: collapse; font-size: 12px; }
  th, td { padding: 2px 8px; text-align: right; white-space: nowrap; }
  .kv th { text-align: left; }
  .diff { font-size: 12px; overflow-x: auto; background: var(--panel2); padding: 8px; }
</style>
