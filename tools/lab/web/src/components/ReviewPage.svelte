<script lang="ts">
  // Review page (WEB_API.md section 12): open a session of the data root, look at it, fix its labels, save.
  // Edits are sample indices; the server applies each one (one implementation of the rules) and the page keeps the
  // undo history. Nothing is written until Save.
  import { onMount } from 'svelte';
  import { ApiError, isAbort } from '../lib/api';
  import { app } from '../lib/store.svelte';
  import {
    ramp,
    reviewApi,
    type EditOp,
    type ImportResult,
    type ReviewEnvelope,
    type ReviewLabel,
    type ReviewSpectrogram,
    type ReviewStream,
    type SaveResult,
    type SessionInfo,
    type SessionSummary,
  } from '../lib/review';
  import type { Pace } from '../lib/types';

  const WAVE_H = 170;
  const SPEC_H = 140;
  const NFFT = 256;

  let sessions = $state.raw<SessionSummary[]>([]);
  let listError = $state<string | null>(null);
  let session = $state.raw<SessionInfo | null>(null);
  let stream = $state<ReviewStream>('adc_raw');
  let specCh = $state(0);
  let labels = $state.raw<ReviewLabel[]>([]);
  let savedJson = $state('[]');
  let version = $state('');
  let undoStack = $state.raw<ReviewLabel[][]>([]);
  let redoStack = $state.raw<ReviewLabel[][]>([]);
  let sel = $state<number | null>(null);
  let cursor = $state(0);
  let v0 = $state(0);
  let v1 = $state(1);
  let width = $state(800);
  let env = $state.raw<ReviewEnvelope | null>(null);
  let spec = $state.raw<ReviewSpectrogram | null>(null);
  let busy = $state(false);
  let saveResult = $state.raw<SaveResult | null>(null);
  let drag = $state.raw<{ n: number; edge: 'start' | 'end'; i: number } | null>(null);
  let waveCanvas = $state<HTMLCanvasElement | null>(null);
  let specCanvas = $state<HTMLCanvasElement | null>(null);

  // side panel fields
  let fLabel = $state('walk');
  let fPerson = $state('');
  let fPace = $state<'' | Pace>('');
  let fShoes = $state<'' | 'true' | 'false'>('');

  // SD import
  let sdPath = $state('');
  let importing = $state(false);
  let importOut = $state.raw<{ results: ImportResult[]; summary: Record<string, number> } | null>(null);

  const info = $derived(session?.streams[stream] ?? null);
  const frames = $derived(info?.frames ?? 0);
  const rate = $derived(info?.sample_rate ?? 1);
  const dirty = $derived(JSON.stringify(labels) !== savedJson);
  const selected = $derived(sel !== null ? (labels[sel] ?? null) : null);
  const span = $derived(Math.max(1, v1 - v0));
  const peerStream = $derived<ReviewStream>(stream === 'adc_raw' ? 'accel' : 'adc_raw');
  const allowed = $derived(session?.labels_allowed ?? []);
  /** Labels whose text is not in the protocol's list (older sessions): marked, and a save needs them retagged. */
  const offList = $derived(labels.flatMap((l, n) => (allowed.includes(l.label) ? [] : [n])));

  // the rail and the Back button ask before leaving with unsaved edits (App.svelte reads this flag)
  $effect(() => {
    app.reviewDirty = dirty;
  });

  function err(e: unknown): void {
    if (isAbort(e)) return;
    app.toast(e instanceof ApiError ? e.message : String(e), 'error');
  }

  async function loadList(): Promise<void> {
    try {
      sessions = (await reviewApi.sessions()).sessions;
      listError = null;
    } catch (e) {
      listError = e instanceof ApiError ? e.message : String(e);
    }
  }

  async function openSession(name: string, keepStream = false): Promise<void> {
    if (dirty && !confirm('The labels have unsaved changes. Open another session and lose them?')) return;
    try {
      const s = await reviewApi.open(name);
      session = s;
      if (!keepStream || !s.streams[stream]) stream = s.streams.adc_raw ? 'adc_raw' : 'accel';
      resetStream();
    } catch (e) {
      err(e);
    }
  }

  function resetStream(): void {
    const st = session?.streams[stream];
    labels = st?.labels ?? [];
    savedJson = JSON.stringify(labels);
    version = st?.version ?? '';
    undoStack = [];
    redoStack = [];
    sel = null;
    saveResult = null;
    specCh = 0;
    v0 = 0;
    v1 = Math.max(1, st?.frames ?? 1);
    cursor = 0;
    const list = session?.labels_allowed ?? [];
    if (list.length && !list.includes(fLabel)) fLabel = list.includes('walk') ? 'walk' : list[0];
  }

  function switchStream(s: ReviewStream): void {
    if (s === stream) return;
    if (dirty && !confirm('The labels of this stream have unsaved changes. Switch and lose them?')) return;
    stream = s;
    resetStream();
  }

  // ------------------------------------------------------------------------------------------- views

  let ctrl: AbortController | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;

  $effect(() => {
    const name = session?.name;
    const deps = [stream, v0, v1, width, specCh, frames];
    if (!name || !frames) return;
    clearTimeout(timer);
    timer = setTimeout(() => void fetchViews(name, deps), 60);
  });

  async function fetchViews(name: string, _deps: unknown[]): Promise<void> {
    ctrl?.abort();
    const c = new AbortController();
    ctrl = c;
    const cols = Math.max(50, Math.min(4000, Math.round(width)));
    try {
      const [e, s] = await Promise.all([
        reviewApi.envelope(name, { stream, i0: v0, i1: v1, columns: cols }, c.signal),
        reviewApi.spectrogram(name, { stream, ch: specCh, i0: v0, i1: v1, columns: Math.min(cols, 800), nfft: NFFT }, c.signal),
      ]);
      env = e;
      spec = s;
    } catch (e) {
      err(e);
    }
  }

  function cssVar(name: string): string {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888';
  }

  $effect(() => {
    const e = env;
    const cv = waveCanvas;
    if (!cv || !e) return;
    const dpr = window.devicePixelRatio || 1;
    cv.width = Math.round(width * dpr);
    cv.height = Math.round(WAVE_H * dpr);
    const g = cv.getContext('2d');
    if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, width, WAVE_H);
    const n = e.min.length;
    const laneH = WAVE_H / Math.max(1, n);
    const x = (i: number) => ((i - e.i0) / Math.max(1, e.i1 - e.i0)) * width;
    for (let c = 0; c < n; c++) {
      const lo = e.min[c];
      const hi = e.max[c];
      let a = Infinity;
      let b = -Infinity;
      for (let k = 0; k < lo.length; k++) {
        if (lo[k] !== null) a = Math.min(a, lo[k] as number);
        if (hi[k] !== null) b = Math.max(b, hi[k] as number);
      }
      if (!Number.isFinite(a) || !Number.isFinite(b)) continue;
      const pad = (b - a) * 0.05 || 1;
      a -= pad;
      b += pad;
      const top = c * laneH;
      const y = (v: number) => top + laneH - ((v - a) / (b - a)) * laneH;
      g.strokeStyle = cssVar(`--ch${c % 3}`);
      g.lineWidth = 1;
      g.beginPath();
      for (let k = 0; k < lo.length; k++) {
        if (lo[k] === null || hi[k] === null) continue;
        const px = Math.round(x((e.edges[k] + e.edges[k + 1]) / 2)) + 0.5;
        g.moveTo(px, y(hi[k] as number));
        g.lineTo(px, Math.max(y(lo[k] as number), y(hi[k] as number) + 1));
      }
      g.stroke();
      g.fillStyle = cssVar('--muted');
      g.font = '11px ui-monospace, monospace';
      g.fillText(`ch${c} ${e.units[c] ?? ''}`, 4, top + 12);
    }
  });

  $effect(() => {
    const s = spec;
    const cv = specCanvas;
    if (!cv || !s || s.power_db.length === 0) return;
    const cols = s.power_db.length;
    const bins = s.freq_hz.length;
    const vals: number[] = [];
    for (const row of s.power_db) for (const v of row) if (v !== null) vals.push(v);
    vals.sort((p, q) => p - q);
    const lo = vals[Math.floor(vals.length * 0.05)] ?? 0;
    const hi = vals[Math.floor(vals.length * 0.995)] ?? 1;
    const img = new ImageData(cols, bins);
    for (let c = 0; c < cols; c++) {
      for (let b = 0; b < bins; b++) {
        const v = s.power_db[c][b];
        const o = ((bins - 1 - b) * cols + c) * 4;
        if (v === null) {
          img.data[o + 3] = 0;
          continue;
        }
        const [r, gg, bb] = ramp((v - lo) / Math.max(1e-9, hi - lo));
        img.data[o] = r;
        img.data[o + 1] = gg;
        img.data[o + 2] = bb;
        img.data[o + 3] = 255;
      }
    }
    const off = document.createElement('canvas');
    off.width = cols;
    off.height = bins;
    off.getContext('2d')?.putImageData(img, 0, 0);
    const dpr = window.devicePixelRatio || 1;
    cv.width = Math.round(width * dpr);
    cv.height = Math.round(SPEC_H * dpr);
    const g = cv.getContext('2d');
    if (!g) return;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, width, SPEC_H);
    g.imageSmoothingEnabled = false;
    // columns are centred on center_index; place the image between the first and last centre
    const x = (i: number) => ((i - s.i0) / Math.max(1, s.i1 - s.i0)) * width;
    const half = cols > 1 ? (s.center_index[1] - s.center_index[0]) / 2 : s.nfft / 2;
    const xa = x(s.center_index[0] - half);
    const xb = x(s.center_index[cols - 1] + half);
    g.drawImage(off, xa, 0, Math.max(1, xb - xa), SPEC_H);
    g.fillStyle = '#fff';
    g.font = '11px ui-monospace, monospace';
    g.fillText(`${Math.round(s.freq_hz[bins - 1])} Hz`, 4, 12);
    g.fillText('0 Hz', 4, SPEC_H - 4);
  });

  // ---------------------------------------------------------------------------- zoom, pan, cursor

  function setView(a: number, b: number): void {
    const len = Math.max(Math.min(frames, 50), Math.min(frames, Math.round(b - a)));
    let s = Math.round(a);
    s = Math.max(0, Math.min(frames - len, s));
    v0 = s;
    v1 = s + len;
  }

  /** Wheel zoom: the sample under the pointer stays where it is. */
  function zoom(factor: number, around = cursor): void {
    const c = Math.min(Math.max(around, v0), v1);
    const f = (c - v0) / span;
    const len = span * factor;
    setView(c - f * len, c - f * len + len);
  }

  /** Button and key zoom: centred on the selected label, else on the cursor. */
  function zoomCentred(factor: number): void {
    const l = sel !== null ? labels[sel] : undefined;
    const c = l ? (l.i0 + l.i1) / 2 : cursor;
    const len = span * factor;
    setView(c - len / 2, c + len / 2);
  }

  const toSample = (clientX: number, el: HTMLElement): number => {
    const r = el.getBoundingClientRect();
    return Math.round(v0 + ((clientX - r.left) / Math.max(1, r.width)) * span);
  };
  const pct = (i: number): number => ((i - v0) / span) * 100;

  let pan: { x: number; v0: number; moved: boolean } | null = null;

  function onPointerDown(e: PointerEvent): void {
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    pan = { x: e.clientX, v0, moved: false };
  }
  function onPointerMove(e: PointerEvent): void {
    if (!pan) return;
    const dx = e.clientX - pan.x;
    if (Math.abs(dx) > 3) pan.moved = true;
    if (pan.moved) setView(pan.v0 - (dx / Math.max(1, width)) * span, pan.v0 - (dx / Math.max(1, width)) * span + span);
  }
  function onPointerUp(e: PointerEvent): void {
    if (pan && !pan.moved) cursor = Math.max(0, Math.min(frames, toSample(e.clientX, e.currentTarget as HTMLElement)));
    pan = null;
  }
  function onWheel(e: WheelEvent): void {
    e.preventDefault();
    zoom(e.deltaY > 0 ? 1.25 : 0.8, toSample(e.clientX, e.currentTarget as HTMLElement));
  }
  function onTimelineKey(e: KeyboardEvent): void {
    const step = e.shiftKey ? Math.max(1, Math.round(span / 20)) : Math.max(1, Math.round(span / 200));
    if (e.key === 'ArrowLeft') cursor = Math.max(0, cursor - step);
    else if (e.key === 'ArrowRight') cursor = Math.min(frames, cursor + step);
    else if (e.key === '+' || e.key === '=') zoomCentred(0.5);
    else if (e.key === '-') zoomCentred(2);
    else return;
    e.preventDefault();
  }

  // ------------------------------------------------------------------------------------ label edits

  async function apply(op: EditOp, select?: (next: ReviewLabel[]) => number | null): Promise<void> {
    if (!session) return;
    busy = true;
    try {
      const r = await reviewApi.edit(session.name, stream, labels, op);
      undoStack = [...undoStack.slice(-199), labels];
      redoStack = [];
      labels = r.labels;
      const next = select ? select(r.labels) : sel !== null && sel < r.labels.length ? sel : null;
      sel = next !== null && next >= 0 ? next : null;
      if (sel !== null) loadFields(sel);
      saveResult = null;
    } catch (e) {
      err(e);
    } finally {
      busy = false;
    }
  }

  function undo(): void {
    if (!undoStack.length) return;
    redoStack = [...redoStack, labels];
    labels = undoStack[undoStack.length - 1];
    undoStack = undoStack.slice(0, -1);
    sel = null;
  }
  function redo(): void {
    if (!redoStack.length) return;
    undoStack = [...undoStack, labels];
    labels = redoStack[redoStack.length - 1];
    redoStack = redoStack.slice(0, -1);
    sel = null;
  }

  /** Every way of selecting a label (its body, an edge grab, a row of the off-list list) goes through here. */
  function choose(n: number): void {
    const l = labels[n];
    if (!l) return;
    sel = n;
    cursor = l.i0;
    loadFields(n);
  }

  /** The side panel shows the selected label's tags. */
  function loadFields(n: number): void {
    const l = labels[n];
    if (!l) return;
    fLabel = l.label;
    fPerson = l.person ?? '';
    fPace = l.pace ?? '';
    fShoes = l.shoes === undefined ? '' : l.shoes ? 'true' : 'false';
  }

  function retag(): void {
    if (sel === null) return;
    const n = sel;
    void apply(
      {
        kind: 'retag',
        n,
        set: {
          label: fLabel,
          person: fPerson || null,
          pace: fPace || null,
          shoes: fShoes === '' ? null : fShoes === 'true',
        },
      },
      () => n,
    );
  }

  function addAtCursor(): void {
    const len = Math.max(1, Math.round(rate * 0.5));
    const i0 = Math.min(cursor, Math.max(0, frames - 1));
    const i1 = Math.min(frames, i0 + len);
    const op: EditOp = { kind: 'add', i0, i1, label: fLabel };
    if (fPerson) op.person = fPerson;
    if (fPace) op.pace = fPace;
    if (fShoes) op.shoes = fShoes === 'true';
    void apply(op, (next) => next.findIndex((l) => l.i0 === i0 && l.i1 === i1 && l.src === 'review'));
  }

  // edge drag: drawn locally while dragging, applied by the server on release
  function edgeDown(e: PointerEvent, n: number, edge: 'start' | 'end'): void {
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    const l = labels[n];
    drag = { n, edge, i: edge === 'start' ? l.i0 : l.i1 };
    choose(n);
  }

  /** Select label n and bring it into view (the off-list rows). */
  function reveal(n: number): void {
    const l = labels[n];
    if (!l) return;
    choose(n);
    if (l.i1 < v0 || l.i0 > v1) {
      const mid = (l.i0 + l.i1) / 2;
      setView(mid - span / 2, mid + span / 2);
    }
  }
  function edgeMove(e: PointerEvent): void {
    if (!drag) return;
    const lane = (e.currentTarget as HTMLElement).closest('.lane') as HTMLElement | null;
    if (!lane) return;
    const l = labels[drag.n];
    let i = Math.max(0, Math.min(frames, toSample(e.clientX, lane)));
    i = drag.edge === 'start' ? Math.min(i, l.i1) : Math.max(i, l.i0);
    drag = { ...drag, i };
  }
  function edgeUp(): void {
    if (!drag) return;
    const d = drag;
    drag = null;
    const l = labels[d.n];
    if ((d.edge === 'start' ? l.i0 : l.i1) === d.i) return;
    void apply({ kind: 'move', n: d.n, edge: d.edge, i: d.i }, (next) =>
      next.findIndex((x) => (d.edge === 'start' ? x.i0 === d.i && x.i1 === l.i1 : x.i0 === l.i0 && x.i1 === d.i)),
    );
  }
  function edgeKey(e: KeyboardEvent, n: number, edge: 'start' | 'end'): void {
    const l = labels[n];
    const step = e.shiftKey ? Math.max(1, Math.round(rate / 10)) : 1;
    const cur = edge === 'start' ? l.i0 : l.i1;
    let i: number;
    if (e.key === 'ArrowLeft') i = cur - step;
    else if (e.key === 'ArrowRight') i = cur + step;
    else return;
    e.preventDefault();
    void apply({ kind: 'move', n, edge, i: Math.max(0, Math.min(frames, i)) }, () => n);
  }

  function shown(l: ReviewLabel, n: number): [number, number] {
    if (drag && drag.n === n) return drag.edge === 'start' ? [drag.i, l.i1] : [l.i0, drag.i];
    return [l.i0, l.i1];
  }

  // ------------------------------------------------------------------------------------------ save

  async function save(): Promise<void> {
    if (!session) return;
    busy = true;
    try {
      const peer = session.streams[peerStream];
      const r = await reviewApi.save(session.name, stream, labels, version, peer?.version ?? null);
      saveResult = r;
      if (r.saved && r.labels && r.version) {
        labels = r.labels;
        savedJson = JSON.stringify(r.labels);
        version = r.version;
        // keep both streams' labels and versions in step with the disk (switching stream shows the synced list)
        const streams = { ...session.streams };
        const own = streams[stream];
        if (own) streams[stream] = { ...own, labels: r.labels, version: r.version, backup: true };
        const p = r.peer ? streams[r.peer.stream] : undefined;
        if (r.peer && p) streams[r.peer.stream] = { ...p, labels: r.peer.labels, version: r.peer.version, backup: true };
        session = { ...session, streams };
        const both = r.peer ? ` and ${r.peer.sidecar}` : '';
        app.toast(`Saved ${r.sidecar}${both}${r.validation?.ok ? '' : ' (the session does not validate: see the result)'}.`, r.validation?.ok ? 'info' : 'error');
      }
    } catch (e) {
      err(e);
    } finally {
      busy = false;
    }
  }

  function onKey(e: KeyboardEvent): void {
    const t = e.target as HTMLElement | null;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'SELECT' || t.tagName === 'TEXTAREA')) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
      e.preventDefault();
      if (e.shiftKey) redo();
      else undo();
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') {
      e.preventDefault();
      redo();
    }
  }

  async function importSd(): Promise<void> {
    importing = true;
    try {
      importOut = await reviewApi.importSd(sdPath.trim());
      await loadList();
    } catch (e) {
      err(e);
    } finally {
      importing = false;
    }
  }

  const fmtS = (i: number): string => `${(i / rate).toFixed(3)} s`;

  onMount(() => {
    void loadList();
    const wanted = new URLSearchParams(location.search).get('session');
    if (wanted) void openSession(wanted);
    const beforeUnload = (e: BeforeUnloadEvent) => {
      if (dirty) e.preventDefault();
    };
    window.addEventListener('beforeunload', beforeUnload);
    return () => {
      window.removeEventListener('beforeunload', beforeUnload);
      app.reviewDirty = false;
    };
  });
</script>

<svelte:window onkeydown={onKey} />

<div class="review">
  <aside class="side">
    <section class="card">
      <header>
        <h2>Sessions</h2>
        <span class="grow"></span>
        <button onclick={() => void loadList()}>Refresh</button>
      </header>
      {#if listError}
        <div class="banner">{listError}</div>
      {:else if sessions.length === 0}
        <div class="muted">No session with a sidecar in the data root yet.</div>
      {/if}
      <ul class="slist">
        {#each sessions as s (s.name)}
          <li>
            <button class:active={session?.name === s.name} onclick={() => void openSession(s.name)}>
              <span class="mono">{s.name}</span>
              <small class="muted">
                {s.streams.map((x) => `${x.stream}${x.labels != null ? ` · ${x.labels} labels` : ''}`).join(' | ')}{s.repo_copy ? ' · in data/' : ''}
              </small>
            </button>
          </li>
        {/each}
      </ul>
    </section>

    <section class="card">
      <header><h2>Import from SD</h2></header>
      <label class="field">
        <span>Folder on the SD card (full path)</span>
        <input class="mono" bind:value={sdPath} placeholder="E:\RZ" />
      </label>
      <div class="row" style="margin-top:8px">
        <button class="primary" disabled={importing || !sdPath.trim()} onclick={() => void importSd()}>{importing ? 'Importing...' : 'Import'}</button>
      </div>
      <p class="muted small">Every session folder is validated first. Invalid ones are not imported; a session the data root already has is skipped, never overwritten. Valid sidecars are copied to the repository's data/.</p>
      {#if importOut}
        <div class="small">
          {Object.entries(importOut.summary).map(([k, v]) => `${v} ${k}`).join(' · ')}
        </div>
        <ul class="results">
          {#each importOut.results as r (r.source)}
            <li>
              <span class="chip {r.status === 'imported' ? 'ok' : r.status === 'skipped' ? 'warn' : 'err'}">{r.status}</span>
              <span class="mono">{r.session}</span>
              {#each r.problems as p, k (k)}<div class="muted small">{p}</div>{/each}
              {#each r.warnings ?? [] as p, k (k)}<div class="muted small">warning: {p}</div>{/each}
              {#if r.note}<div class="muted small">{r.note}</div>{/if}
            </li>
          {/each}
        </ul>
      {/if}
    </section>
  </aside>

  <section class="card mainview">
    {#if !session || !info}
      <div class="muted">Open a session on the left to see its signal and labels.</div>
    {:else}
      <header>
        <h2 class="mono">{session.name}</h2>
        <span class="grow"></span>
        {#if dirty}<span class="chip warn" title="Not saved yet">unsaved changes</span>{:else}<span class="chip ok">saved</span>{/if}
        {#each ['adc_raw', 'accel'] as const as s (s)}
          {#if session.streams[s]}
            <button class:primary={stream === s} onclick={() => switchStream(s)}>{s}</button>
          {/if}
        {/each}
      </header>
      {#if !info.frames}
        <div class="banner">This stream has a sidecar but no WAV file: nothing to show.</div>
      {:else}
        <div class="toolbar row">
          <button onclick={() => zoomCentred(0.5)} title="Zoom in on the selected label, else the cursor (+)">Zoom in</button>
          <button onclick={() => zoomCentred(2)} title="Zoom out around the selected label, else the cursor (-)">Zoom out</button>
          <button onclick={() => setView(0, frames)}>Fit all</button>
          <span class="muted small mono">view {fmtS(v0)} to {fmtS(v1)} · cursor {cursor} ({fmtS(cursor)}) · {info.sample_rate} Hz · {frames} frames</span>
          <span class="grow" style="flex:1"></span>
          <label class="field inline">
            <span>Spectrogram ch</span>
            <select bind:value={specCh}>
              {#each info.channels as c (c.ch)}<option value={c.ch}>ch{c.ch} ({c.units})</option>{/each}
            </select>
          </label>
        </div>

        <div class="timeline" bind:clientWidth={width}>
          <div
            class="plot"
            role="slider"
            tabindex="0"
            aria-label="Signal: click to set the cursor, drag to pan, wheel to zoom"
            aria-valuemin={0}
            aria-valuemax={frames}
            aria-valuenow={cursor}
            onpointerdown={onPointerDown}
            onpointermove={onPointerMove}
            onpointerup={onPointerUp}
            onwheel={onWheel}
            onkeydown={onTimelineKey}
          >
            <canvas bind:this={waveCanvas} style="width:100%;height:{WAVE_H}px"></canvas>
            <canvas bind:this={specCanvas} style="width:100%;height:{SPEC_H}px"></canvas>
            {#if cursor >= v0 && cursor <= v1}<div class="cursor" style="left:{pct(cursor)}%"></div>{/if}
            {#each labels as l, n (n)}
              {@const [a, b] = shown(l, n)}
              {#if b >= v0 && a <= v1}
                {@const ca = Math.max(a, v0)}
                {@const cb = Math.min(b, v1)}
                <div class="shade" class:sel={sel === n} style="left:{pct(ca)}%;width:{Math.max(0.1, pct(cb) - pct(ca))}%"></div>
              {/if}
            {/each}
          </div>
          <div class="lane" aria-label="Labels">
            {#each labels as l, n (n)}
              {@const [a, b] = shown(l, n)}
              {#if b >= v0 && a <= v1}
                {@const off = offList.includes(n)}
                <div class="span" class:sel={sel === n} class:off style="left:{pct(a)}%;width:{Math.max(0.2, pct(b) - pct(a))}%">
                  <button class="body" onclick={() => choose(n)} title="{off ? 'Not in the protocol\'s label list: retag it before saving. ' : ''}{l.label} {l.person ?? ''} {fmtS(l.i0)} to {fmtS(l.i1)} · src {l.src ?? '-'}">
                    {#if off}<span class="badge" aria-label="not in the label list">!</span>{/if}{l.label}{l.person ? ` ${l.person}` : ''}
                  </button>
                  <span
                    class="edge start"
                    role="slider"
                    tabindex="0"
                    aria-label="Start of label {n + 1} (arrow keys move it)"
                    aria-valuemin={0}
                    aria-valuemax={frames}
                    aria-valuenow={a}
                    onpointerdown={(e) => edgeDown(e, n, 'start')}
                    onpointermove={edgeMove}
                    onpointerup={edgeUp}
                    onkeydown={(e) => edgeKey(e, n, 'start')}
                  ></span>
                  <span
                    class="edge end"
                    role="slider"
                    tabindex="0"
                    aria-label="End of label {n + 1} (arrow keys move it)"
                    aria-valuemin={0}
                    aria-valuemax={frames}
                    aria-valuenow={b}
                    onpointerdown={(e) => edgeDown(e, n, 'end')}
                    onpointermove={edgeMove}
                    onpointerup={edgeUp}
                    onkeydown={(e) => edgeKey(e, n, 'end')}
                  ></span>
                </div>
              {/if}
            {/each}
          </div>
        </div>

        <div class="editor">
          <div class="row">
            <button onclick={undo} disabled={!undoStack.length || busy} title="Ctrl+Z">Undo</button>
            <button onclick={redo} disabled={!redoStack.length || busy} title="Ctrl+Shift+Z">Redo</button>
            <button onclick={addAtCursor} disabled={busy} title="A 0.5 s label at the cursor with the fields on the right">Add at cursor</button>
            <button onclick={() => sel !== null && void apply({ kind: 'split', n: sel, i: cursor })} disabled={sel === null || busy}>Split at cursor</button>
            <button onclick={() => sel !== null && void apply({ kind: 'merge', n: sel }, () => sel)} disabled={sel === null || sel >= labels.length - 1 || busy}>Merge with next</button>
            <button class="danger" onclick={() => sel !== null && void apply({ kind: 'delete', n: sel }, () => null)} disabled={sel === null || busy}>Delete</button>
            <span class="grow" style="flex:1"></span>
            <button class="primary" onclick={() => void save()} disabled={!dirty || busy}>Save</button>
          </div>

          <div class="fields row">
            <label class="field"><span>Label</span>
              <select class="mono" bind:value={fLabel} disabled={!allowed.length} title={session.labels_note ?? 'The labels of protocol ' + (session.protocol ?? '?')}>
                {#each allowed as s (s)}<option value={s}>{s}</option>{/each}
                {#if fLabel && !allowed.includes(fLabel)}<option value={fLabel} disabled>{fLabel} (not in the list)</option>{/if}
              </select>
            </label>
            <label class="field"><span>Person</span>
              <select bind:value={fPerson}>
                <option value="">none</option>
                {#each session.persons as p (p)}<option value={p}>{p}</option>{/each}
                {#if fPerson && !session.persons.includes(fPerson)}<option value={fPerson}>{fPerson} (not in the session's list)</option>{/if}
              </select>
            </label>
            <label class="field"><span>Pace</span>
              <select bind:value={fPace}>
                <option value="">none</option><option value="slow">slow</option><option value="normal">normal</option><option value="fast">fast</option>
              </select>
            </label>
            <label class="field"><span>Shoes</span>
              <select bind:value={fShoes}>
                <option value="">not set</option><option value="true">on</option><option value="false">off</option>
              </select>
            </label>
            <button onclick={retag} disabled={sel === null || busy}>Apply to selected</button>
          </div>
          {#if selected}
            <div class="muted small mono">
              #{(sel ?? 0) + 1}: i0 {selected.i0} · i1 {selected.i1} ({fmtS(selected.i0)} to {fmtS(selected.i1)}) · src {selected.src ?? '-'}{selected.unc_ms != null ? ` · ±${selected.unc_ms} ms` : ''}
            </div>
          {/if}
          {#if session.labels_note}<div class="banner small">{session.labels_note}.{allowed.length ? '' : ' Labels cannot be added, retagged or saved.'}</div>{/if}
          {#if offList.length}
            <div class="banner small">
              {offList.length} label(s) are not in this protocol's list ({allowed.join(', ') || 'none'}), marked "!". Retag them before saving:
              <span class="offrows">
                {#each offList.slice(0, 30) as n (n)}
                  <button class="small" onclick={() => reveal(n)}>#{n + 1} {labels[n].label} {fmtS(labels[n].i0)}</button>
                {/each}
                {#if offList.length > 30}<span class="muted">and {offList.length - 30} more</span>{/if}
              </span>
            </div>
          {/if}
          <p class="muted small">Saving writes the labels into both streams' sidecars (adc_raw and accel), placed through the device clock, so the two stay in step. A label edited here keeps its src (the schema has no "edit" source); moving an edge drops its live timing uncertainty. A label added here gets src "review". Save keeps the previous sidecar as .bak and validates the session.</p>

          {#if saveResult}
            <div class="result">
              {#if !saveResult.saved}
                <div class="banner">Not saved: the sidecar would not validate.</div>
                {#each saveResult.problems as p, k (k)}<div class="small mono">{p}</div>{/each}
              {:else}
                <div>
                  <span class="chip ok">saved</span> {saveResult.sidecar} (previous version: {saveResult.backup})
                  · validation <span class="chip {saveResult.validation?.ok ? 'ok' : 'err'}">{saveResult.validation?.ok ? 'ok' : 'failed'}</span>
                  · data/ copy: {saveResult.repo_copy.updated ? 'updated' : saveResult.repo_copy.reason}
                </div>
                {#each saveResult.validation?.problems ?? [] as p, k (k)}<div class="small mono">{p}</div>{/each}
                {#each saveResult.validation?.warnings ?? [] as p, k (k)}<div class="small muted">{p}</div>{/each}
                {#each saveResult.warnings ?? [] as p, k (k)}<div class="small muted">{p}</div>{/each}
              {/if}
              {#if saveResult.note}<div class="small muted">{saveResult.note}</div>{/if}
            </div>
          {/if}
        </div>
      {/if}
    {/if}
  </section>
</div>

<style>
  .review {
    display: grid;
    grid-template-columns: minmax(240px, 320px) minmax(0, 1fr);
    gap: 12px;
    align-items: start;
  }
  @media (max-width: 900px) {
    .review {
      grid-template-columns: 1fr;
    }
  }
  .side {
    display: grid;
    gap: 12px;
  }
  .slist {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 4px;
    max-height: 50vh;
    overflow: auto;
  }
  .slist button {
    width: 100%;
    text-align: left;
    display: grid;
    gap: 2px;
  }
  .slist button.active {
    border-color: var(--accent);
  }
  .results {
    list-style: none;
    padding: 0;
    margin: 6px 0 0;
    display: grid;
    gap: 6px;
  }
  .small {
    font-size: 12px;
  }
  .mainview {
    min-width: 0;
  }
  .toolbar {
    margin-bottom: 8px;
    align-items: center;
  }
  .field.inline {
    flex-direction: row;
    align-items: center;
    gap: 6px;
  }
  .timeline {
    position: relative;
    user-select: none;
    min-width: 0;
    max-width: 100%;
    overflow: hidden;
  }
  .plot {
    position: relative;
    overflow: hidden;
    background: var(--panel2);
    border: 1px solid var(--line);
    cursor: crosshair;
    touch-action: none;
  }
  .plot canvas {
    display: block;
  }
  .cursor {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 1px;
    background: var(--warn);
    pointer-events: none;
  }
  .shade {
    position: absolute;
    top: 0;
    bottom: 0;
    background: color-mix(in srgb, var(--accent) 12%, transparent);
    pointer-events: none;
  }
  .shade.sel {
    background: color-mix(in srgb, var(--accent) 24%, transparent);
  }
  .lane {
    position: relative;
    height: 34px;
    margin-top: 4px;
    background: var(--panel2);
    border: 1px solid var(--line);
    overflow: hidden;
  }
  .span {
    position: absolute;
    top: 3px;
    bottom: 3px;
    min-width: 6px;
  }
  .span .body {
    width: 100%;
    height: 100%;
    padding: 0 8px;
    font-size: 11px;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    background: color-mix(in srgb, var(--accent) 22%, var(--panel));
    border: 1px solid var(--accent);
    border-radius: 3px;
  }
  .span.off .body {
    border-color: var(--warn);
    border-style: dashed;
  }
  .badge {
    display: inline-block;
    margin-right: 4px;
    padding: 0 4px;
    border-radius: 3px;
    background: var(--warn);
    color: var(--bg);
    font-weight: 700;
  }
  .offrows {
    display: inline-flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-left: 4px;
  }
  .span.sel .body {
    background: color-mix(in srgb, var(--accent) 45%, var(--panel));
  }
  .edge {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 7px;
    cursor: ew-resize;
    background: var(--accent);
    opacity: 0.7;
    touch-action: none;
  }
  .edge.start {
    left: -3px;
  }
  .edge.end {
    right: -3px;
  }
  .edge:focus-visible {
    outline: 2px solid var(--warn);
  }
  .editor {
    margin-top: 10px;
    display: grid;
    gap: 8px;
  }
  .fields {
    align-items: end;
  }
  .result {
    border-top: 1px solid var(--line);
    padding-top: 8px;
    display: grid;
    gap: 4px;
  }
</style>
