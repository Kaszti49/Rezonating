<script lang="ts">
  // The session form and Start (WEB_API.md 9.3). Errors from a 422 are shown next to their fields; the server never
  // echoes a rejected value and neither does this page.
  import { api, ApiError } from '../lib/api';
  import { app, chName } from '../lib/store.svelte';
  import { chanKey, MAX_PERSONS, recForm as f } from '../lib/recform.svelte';
  import type { ChannelDefaults, ProtocolInfo, RecordOptions } from '../lib/types';

  let { options }: { options: RecordOptions } = $props();

  let personInput = $state('');
  let personErr = $state('');
  let starting = $state(false);

  const personRe = $derived.by(() => {
    try {
      return new RegExp(options.person_pattern || '^P\\d+$');
    } catch {
      return /^P\d+$/;
    }
  });
  const streams = $derived((options.node?.streams ?? []).filter((s) => s.recordable));
  const hosts = $derived(options.marker.hosts);
  const blockers = $derived(options.blockers.filter((b) => !b.code.startsWith('data_root') && b.code !== 'no_data_root'));

  $effect(() => {
    f.sync(options);
  });

  // The chosen protocol's steps, for the line under the picker (and to show a broken protocol file before Start).
  let proto = $state.raw<ProtocolInfo | null>(null);
  let protoErr = $state('');
  $effect(() => {
    const name = f.protocol;
    if (!name) return;
    let gone = false;
    api.protocol(name).then(
      (p) => {
        if (gone) return;
        proto = p;
        protoErr = '';
      },
      (e: unknown) => {
        if (gone) return;
        proto = null;
        protoErr = e instanceof ApiError ? e.message : String(e);
      },
    );
    return () => {
      gone = true;
    };
  });

  function protoSummary(p: ProtocolInfo): string {
    const parts: string[] = [];
    for (const b of p.blocks) {
      for (const s of b.steps) {
        if (s.kind === 'timed') parts.push(`${s.label} ${s.duration_s} s`);
      }
      if (b.for_each_person) {
        const n = b.steps.reduce((a, s) => a + (s.kind === 'passes' ? s.passes : 0), 0);
        parts.push(`per person: ${b.steps.length} steps, ${n} passes`);
      }
    }
    return parts.join(' · ');
  }

  function addPerson(): void {
    // Accept "p3" as "P3". A refused entry is cleared, never shown back (it may be a real name).
    const v = personInput.trim().replace(/^p(?=\d+$)/, 'P');
    personInput = '';
    personErr = '';
    if (!v) return;
    if (!personRe.test(v)) {
      personErr = 'Only pseudonyms like P1, P2 (the letter P and a number). The entry was cleared.';
      return;
    }
    if (f.persons.includes(v)) {
      personErr = `${v} is already in the list.`;
      return;
    }
    if (f.persons.length >= MAX_PERSONS) {
      personErr = `At most ${MAX_PERSONS} persons.`;
      return;
    }
    f.persons = [...f.persons, v];
    delete f.errors.persons;
  }

  function removePerson(p: string): void {
    f.persons = f.persons.filter((x) => x !== p);
  }

  async function start(): Promise<void> {
    const { form, keys } = f.build(options);
    if (!f.precheck(form, keys, f.filled(keys))) return;
    starting = true;
    try {
      const r = await api.recStart(form);
      f.errors = {};
      f.save();
      app.applyRecording(r);
    } catch (e) {
      const err = e instanceof ApiError ? e : null;
      if (err && err.status === 422) f.applyDetails(err.details, keys, err.message);
      else f.errors = { form: err ? err.message : String(e) };
    } finally {
      starting = false;
    }
  }

  function defaultsText(d: ChannelDefaults | null | undefined, k: keyof ChannelDefaults): string {
    const v = d?.[k];
    return v === null || v === undefined ? '' : String(v);
  }
</script>

{#snippet err(key: string)}
  {#if f.errors[key]}<div class="field-err" role="alert">{f.errors[key]}</div>{/if}
{/snippet}

<section class="card">
  <header>
    <h2>New session</h2>
    {#if options.node?.simulated}<span class="chip warn" title="Simulated sessions are not copied to the repository's data/">simulated</span>{/if}
    {#if options.node}<span class="mono muted">{options.node.node_id} · {options.node.fw_version}</span>{/if}
  </header>

  <form
    class="stack"
    onsubmit={(e) => {
      e.preventDefault();
      void start();
    }}
  >
    <div class="row">
      <label class="field" style="flex:1; min-width:150px">
        <span>Site (required)</span>
        <input bind:value={f.site} maxlength="64" placeholder="home-a" aria-invalid={!!f.errors.site} />
        {@render err('site')}
      </label>
      <label class="field" style="flex:1; min-width:150px">
        <span>Room (required)</span>
        <input bind:value={f.room} maxlength="64" placeholder="kitchen" aria-invalid={!!f.errors.room} />
        {@render err('room')}
      </label>
      <label class="field" style="flex:1; min-width:150px">
        <span>Floor</span>
        <input bind:value={f.floor} maxlength="40" placeholder="ground, laminate" aria-invalid={!!f.errors.floor} />
        {@render err('floor')}
      </label>
      <label class="field" style="flex:2; min-width:200px">
        <span>Surface (written to every channel)</span>
        <input bind:value={f.surface} maxlength="120" placeholder="laminate on concrete slab" aria-invalid={!!f.errors.surface} />
        {@render err('surface')}
      </label>
    </div>

    <div class="row">
      <div class="field" style="min-width:180px; max-width:340px">
        <span id="rz-protocol-label">Protocol</span>
        <select bind:value={f.protocol} aria-labelledby="rz-protocol-label" aria-invalid={!!f.errors.protocol}>
          {#each options.protocols as p (p)}<option value={p}>{p}</option>{/each}
        </select>
        {@render err('protocol')}
        <label style="display:flex; gap:6px; align-items:center; margin-top:4px">
          <input type="checkbox" bind:checked={f.runner} /> run it step by step
        </label>
        {#if proto}
          <span class="muted" title={proto.title}>{protoSummary(proto)}</span>
        {:else if protoErr}
          <div class="field-err" role="alert">{protoErr}</div>
        {/if}
        {@render err('runner')}
      </div>
      <div class="field" style="flex:1; min-width:260px">
        <span>Persons (pseudonyms only: P1, P2 …; at most {MAX_PERSONS})</span>
        <div class="persons">
          {#each f.persons as p (p)}
            <span class="pchip">{p}<button type="button" onclick={() => removePerson(p)} aria-label="Remove {p}">&times;</button></span>
          {/each}
          <input
            class="mono"
            style="width:7em"
            bind:value={personInput}
            placeholder="P1"
            autocomplete="off"
            aria-label="Add a pseudonym"
            aria-invalid={!!personErr || !!f.errors.persons}
            onkeydown={(e) => {
              if (e.key === 'Enter' || e.key === ',') {
                e.preventDefault();
                addPerson();
              }
            }}
          />
          <button type="button" onclick={addPerson} disabled={!personInput.trim()}>Add</button>
        </div>
        {#if personErr}<div class="field-err" role="alert">{personErr}</div>{/if}
        {@render err('persons')}
      </div>
    </div>

    <div>
      <strong>Sensors</strong>
      <span class="muted"> · where each recorded channel sits, in metres (x and y required, z optional). Empty head, serial, port and mount take the node's defaults (shown greyed).</span>
      {@render err('streams')}
      {@render err('sensors')}
      {#if !options.node}
        <div class="empty">Connect to a node (Device page) to fill in the sensors.</div>
      {/if}
      {#each streams as s (s.name)}
        <div style="margin-top:10px">
          <div class="row" style="align-items:center; gap:14px">
            <label style="display:flex; gap:6px; align-items:center">
              <input type="checkbox" bind:checked={f.streams[s.name]} />
              <strong class="mono">{s.name}</strong>
            </label>
            <span class="muted mono">{s.n_ch} ch · {s.nominal_hz} Hz · {s.clock}</span>
            {#if s.n_ch > 1}
              <label style="display:flex; gap:6px; align-items:center" class="muted">
                <input type="checkbox" bind:checked={f.shared[s.name]} disabled={!f.streams[s.name]} />
                one position for all channels
              </label>
            {/if}
          </div>
          {#if f.streams[s.name]}
            {@const rows = f.shared[s.name] ? [{ ch: '*' as const, d: s.channels[0]?.defaults ?? null }] : s.channels.map((c) => ({ ch: c.ch, d: c.defaults ?? null }))}
            <div style="overflow-x:auto">
              <table class="sensors">
                <thead>
                  <tr>
                    <th>ch</th>
                    <th>x m</th>
                    <th>y m</th>
                    <th>z m</th>
                    <th>head</th>
                    <th>serial</th>
                    <th>port</th>
                    <th>mount</th>
                  </tr>
                </thead>
                <tbody>
                  {#each rows as r (r.ch)}
                    {@const k = chanKey(s.name, r.ch)}
                    {@const c = f.chans[k]}
                    {#if c}
                      <tr>
                        <td class="mono">{r.ch === '*' ? 'all' : chName(s.name, r.ch)}</td>
                        <td><input class="num mono" type="number" step="0.01" bind:value={c.x} aria-label="{s.name} {r.ch} x" aria-invalid={!!f.errors[`sensor:${k}`]} /></td>
                        <td><input class="num mono" type="number" step="0.01" bind:value={c.y} aria-label="{s.name} {r.ch} y" aria-invalid={!!f.errors[`sensor:${k}`]} /></td>
                        <td><input class="num mono" type="number" step="0.01" bind:value={c.z} aria-label="{s.name} {r.ch} z" /></td>
                        <td><input class="mono" bind:value={c.head} maxlength="64" placeholder={defaultsText(r.d, 'head')} aria-label="{s.name} {r.ch} head" /></td>
                        <td><input class="mono" bind:value={c.serial} maxlength="32" placeholder={defaultsText(r.d, 'serial')} aria-label="{s.name} {r.ch} serial" /></td>
                        <td><input class="num mono" type="number" min="1" max="4" bind:value={c.port} placeholder={defaultsText(r.d, 'port')} aria-label="{s.name} {r.ch} port" /></td>
                        <td><input class="mono" bind:value={c.mount} maxlength="32" placeholder={defaultsText(r.d, 'mount')} aria-label="{s.name} {r.ch} mount" /></td>
                      </tr>
                      {#if f.errors[`sensor:${k}`]}
                        <tr><td></td><td colspan="7">{@render err(`sensor:${k}`)}</td></tr>
                      {/if}
                    {/if}
                  {/each}
                </tbody>
              </table>
            </div>
          {/if}
        </div>
      {/each}
    </div>

    <div class="row">
      <label class="field" style="flex:1; min-width:260px">
        <span>Notes (free text, no names; max 500)</span>
        <textarea bind:value={f.notes} maxlength="500" rows="2" aria-invalid={!!f.errors.notes}></textarea>
        {@render err('notes')}
      </label>
      <div class="field" style="min-width:240px">
        <span>Phone marker</span>
        <label style="display:flex; gap:6px; align-items:center">
          <input type="checkbox" bind:checked={f.marker} /> start the phone marker (QR code while recording)
        </label>
        {#if f.marker}
          {#if hosts.length > 1}
            <label class="field" style="margin-top:4px">
              <span>Network the phone is on (this PC's address)</span>
              <select class="mono" bind:value={f.markerHost} aria-invalid={!!f.errors.marker_host}>
                {#each hosts as h (h)}<option value={h}>{h}{h === options.marker.bind ? ' (default)' : ''}</option>{/each}
              </select>
            </label>
          {:else if hosts.length === 1}
            <span class="muted">Listens on <span class="mono">{hosts[0]}</span></span>
          {:else}
            <span class="muted">Listens on <span class="mono">{options.marker.bind}</span> (set in the config)</span>
          {/if}
          {@render err('marker_host')}
        {/if}
      </div>
    </div>

    {#each blockers as b (b.code)}
      <div class="banner"><strong class="mono">{b.code}</strong> · {b.message}</div>
    {/each}
    {@render err('form')}

    <div class="row" style="align-items:center">
      <button class="primary" type="submit" disabled={starting || !options.can_start}>
        {starting ? 'Starting…' : 'Start recording'}
      </button>
      {#if starting}<span class="muted">Stopping and restarting the node's streams; this takes up to 5 s.</span>{/if}
      {#if !options.can_start && !starting}<span class="muted">Start is blocked: see the messages above.</span>{/if}
    </div>
  </form>
</section>
