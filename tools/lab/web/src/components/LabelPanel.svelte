<script lang="ts">
  // Live labels (WEB_API.md 9.5). Space starts and ends a mark: the page sends only the edge, the server stamps the
  // arrival on its own clock. The label form below is the current-label state the next mark takes a snapshot of.
  import { onMount } from 'svelte';
  import { api, ApiError } from '../lib/api';
  import { app } from '../lib/store.svelte';
  import { fmtFixed } from '../lib/format';
  import type { LabelState, Pace } from '../lib/types';

  let { persons }: { persons: string[] } = $props();

  const LABEL_RE = /^[a-z0-9 _.-]{1,40}$/;
  const FALLBACK = ['walk', 'silence'];

  let label = $state('walk');
  let person = $state('');
  let pace = $state('');
  let shoes = $state('');
  let errs = $state<Record<string, string>>({});
  let saved = $state(true);

  const recording = $derived(app.recording?.state === 'recording');
  /** The protocol runner sets label, person, pace and shoes from its current step; the form below waits meanwhile. */
  const byRunner = $derived(recording && app.runnerOn);
  /** A timed step (the silence) is running: the server ends its label when the time is over (WEB_API.md 10.5). */
  const countdownOwns = $derived(byRunner && app.runner?.state === 'countdown');
  const open = $derived(app.marks.find((m) => m.state === 'open') ?? null);
  const marking = $derived(open !== null || app.recording?.marking === true);
  const openFor = $derived(open && app.recording?.elapsed_s != null ? Math.max(0, app.recording.elapsed_s - open.start_s) : null);
  const list = $derived(app.marks.slice().reverse());
  const personChoices = $derived(person && !persons.includes(person) ? [...persons, person] : persons);
  /** The protocol's fixed label list (its YAML's labels plus noise, other, bad): the only labels the server accepts. */
  const allowed = $derived(app.recording?.labels_allowed?.length ? app.recording.labels_allowed : FALLBACK);

  function fill(l: LabelState): void {
    label = l.label;
    person = l.person ?? '';
    pace = l.pace ?? '';
    shoes = l.shoes === null ? '' : l.shoes ? 'yes' : 'no';
    saved = true;
  }

  async function save(): Promise<void> {
    const text = label.trim().toLowerCase();
    errs = {};
    if (!LABEL_RE.test(text)) {
      errs = { label: '1 to 40 characters: a-z, 0-9, space, _ . -' };
      return;
    }
    const body: LabelState = {
      label: text,
      person: person || null,
      pace: (pace || null) as Pace | null,
      shoes: shoes === '' ? null : shoes === 'yes',
    };
    try {
      fill(await api.putLabel(body));
    } catch (e) {
      const err = e instanceof ApiError ? e : null;
      const out: Record<string, string> = {};
      for (const d of err?.details ?? []) {
        const loc = d.loc[0] === 'body' ? d.loc.slice(1) : d.loc;
        const k = typeof loc[0] === 'string' && ['label', 'person', 'pace', 'shoes'].includes(loc[0]) ? loc[0] : 'form';
        out[k] = d.msg.replace(/^Value error, /, '');
      }
      if (Object.keys(out).length === 0) out.form = err ? err.message : String(e);
      errs = out;
      saved = false;
    }
  }

  function changed(): void {
    saved = false;
    void save();
  }

  /** A dropdown gives focus back after a pick, so Space marks again at once (Space is ignored inside a select). */
  function picked(e: Event): void {
    changed();
    (e.currentTarget as HTMLElement).blur();
  }

  /** Space is ignored while typing in a field (inputs, selects, text areas, editable text). */
  function typing(t: EventTarget | null): boolean {
    if (!(t instanceof HTMLElement)) return false;
    return t.isContentEditable || t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement || t instanceof HTMLSelectElement;
  }

  function isSpace(e: KeyboardEvent): boolean {
    return e.code === 'Space' || e.key === ' ';
  }

  function onKeyDown(e: KeyboardEvent): void {
    if (!isSpace(e) || !recording || typing(e.target) || e.ctrlKey || e.altKey || e.metaKey) return;
    e.preventDefault(); // no page scroll, and no click on a focused button (e.g. Stop)
    if (e.repeat || countdownOwns) return; // the countdown ends its own label; the runner card offers Cancel
    void toggle();
  }

  function onKeyUp(e: KeyboardEvent): void {
    // Buttons activate on Space release: block that too while recording.
    if (isSpace(e) && recording && !typing(e.target)) e.preventDefault();
  }

  async function toggle(): Promise<void> {
    try {
      const r = await api.mark('toggle');
      app.applyLabel({ action: r.action, mark: r.mark });
    } catch (e) {
      app.toast(e instanceof ApiError ? e.message : String(e), 'error');
    }
  }

  async function remove(id: number): Promise<void> {
    try {
      await api.deleteLabel(id);
      app.applyLabel({ action: 'delete', mark: { id } });
    } catch (e) {
      app.toast(e instanceof ApiError ? e.message : String(e), 'error');
    }
  }

  onMount(() => {
    void (async () => {
      try {
        fill(await api.getLabel());
      } catch {
        if (app.recording?.label_state) fill(app.recording.label_state);
      }
    })();
  });
</script>

<svelte:window onkeydown={onKeyDown} onkeyup={onKeyUp} />

<section class="card">
  <header>
    <h2>Live labels</h2>
    <span class="grow"></span>
    <span class="muted">{app.marks.length} mark{app.marks.length === 1 ? '' : 's'}</span>
  </header>

  <div class="markbox" class:open={marking} role="status" aria-live="polite">
    {#if !recording}
      <span class="muted">Marks can be set while a recording runs. Set the label for the first mark here.</span>
    {:else if marking}
      <span class="dot rec on"></span>
      <span class="big">MARK OPEN</span>
      {#if open}
        <span class="mono">#{open.id} {open.label}{open.person ? ` · ${open.person}` : ''}{open.pace ? ` · ${open.pace}` : ''} · from {fmtFixed(open.start_s, 2, ' s')}</span>
        {#if openFor != null}<span class="mono muted" aria-live="off">({fmtFixed(openFor, 0, ' s')})</span>{/if}
      {/if}
      <span class="grow" style="flex:1"></span>
      {#if countdownOwns}
        <span>The countdown ends it (cancel it on the runner card)</span>
      {:else}
        <span>Press <kbd>Space</kbd> to end it</span>
        <button onclick={toggle}>End mark</button>
      {/if}
    {:else}
      <span class="big muted">no mark open</span>
      <span class="grow" style="flex:1"></span>
      <span>Press <kbd>Space</kbd> to start a mark</span>
      <button onclick={toggle}>Start mark</button>
    {/if}
  </div>
  {#if recording}
    <div class="muted" style="margin:-4px 0 10px">Space does nothing while the cursor is in a text field or a list: click on an empty part of the page first.</div>
  {/if}

  {#if byRunner}
    <div class="banner" style="margin:0 0 8px">The protocol runner sets label, person, pace and shoes from its current step. The fields below apply again when the runner is stopped.</div>
  {/if}
  <div class="row">
    <label class="field" style="min-width:150px">
      <span>Label</span>
      <select class="mono" bind:value={label} onchange={picked} disabled={byRunner} aria-invalid={!!errs.label}>
        {#each allowed as s (s)}<option value={s}>{s}</option>{/each}
        {#if label && !allowed.includes(label)}<option value={label} disabled>{label} (not in the list)</option>{/if}
      </select>
    </label>
    <label class="field">
      <span>Person</span>
      <select bind:value={person} onchange={picked} disabled={byRunner} aria-invalid={!!errs.person}>
        <option value="">none</option>
        {#each personChoices as p (p)}<option value={p}>{p}</option>{/each}
      </select>
    </label>
    <label class="field">
      <span>Pace</span>
      <select bind:value={pace} onchange={picked} disabled={byRunner}>
        <option value="">—</option>
        <option value="slow">slow</option>
        <option value="normal">normal</option>
        <option value="fast">fast</option>
      </select>
    </label>
    <label class="field">
      <span>Shoes</span>
      <select bind:value={shoes} onchange={picked} disabled={byRunner}>
        <option value="">—</option>
        <option value="yes">yes</option>
        <option value="no">no</option>
      </select>
    </label>
    <span class="muted" style="align-self:center">{saved ? 'saved: the next mark uses this' : 'not saved'}</span>
  </div>
  {#each Object.entries(errs) as [k, v] (k)}<div class="field-err" role="alert">{k === 'form' ? '' : `${k}: `}{v}</div>{/each}
  {#if persons.length === 0}<div class="muted" style="margin-top:4px">Add persons (P1, P2 …) in the session form to pick one here.</div>{/if}

  {#if list.length > 0}
    <div style="overflow-x:auto; margin-top:10px; max-height:320px; overflow-y:auto">
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th class="r">start s</th>
            <th class="r">end s</th>
            <th class="r">length s</th>
            <th>label</th>
            <th>person</th>
            <th>pace</th>
            <th>shoes</th>
            <th>from</th>
            <th></th>
          </tr>
        </thead>
        <tbody class="mono">
          {#each list as m (m.id)}
            <tr>
              <td>{m.id}</td>
              <td class="r">{fmtFixed(m.start_s, 2)}</td>
              <td class="r">{m.state === 'open' ? 'open' : fmtFixed(m.end_s, 2)}</td>
              <td class="r">{m.end_s != null ? fmtFixed(m.end_s - m.start_s, 2) : '—'}</td>
              <td>{m.label}</td>
              <td>{m.person ?? '—'}</td>
              <td>{m.pace ?? '—'}</td>
              <td>{m.shoes === null ? '—' : m.shoes ? 'yes' : 'no'}</td>
              <td>{m.src}{m.rtt_ms != null ? ` (${fmtFixed(m.rtt_ms, 0)} ms)` : ''}</td>
              <td><button class="danger" onclick={() => remove(m.id)} disabled={!recording} aria-label="Delete mark {m.id}">Delete</button></td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <div class="muted" style="margin-top:4px">Times are provisional (server clock); exact sample indices are computed when the recording ends.</div>
  {/if}
</section>
