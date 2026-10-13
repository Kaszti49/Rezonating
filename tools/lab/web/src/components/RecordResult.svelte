<script lang="ts">
  // Result of a recording (WEB_API.md 9.7): from POST /api/record/stop, or `recording.last`.
  import { fmtFixed, fmtInt } from '../lib/format';
  import type { RecordResult } from '../lib/types';

  let { result, fresh }: { result: RecordResult; fresh: boolean } = $props();

  const incomplete = $derived(result.streams.some((s) => s.incomplete));
</script>

<section class="card">
  <header>
    <h2>{fresh ? 'Recording finished' : 'Last recording'}</h2>
    <span class="mono">{result.session}</span>
    <span class="chip {result.ok ? 'ok' : 'err'}">{result.ok ? 'ok' : 'problems'}</span>
    {#if incomplete}<span class="chip err" title="No final STATUS: the sidecars say rzlab: loss=incomplete">loss=incomplete</span>{/if}
    {#if result.ended_by !== 'stop'}<span class="chip warn">ended by {result.ended_by}</span>{/if}
  </header>

  <table>
    <tbody>
      <tr>
        <td class="muted" style="width:10em">stored in</td>
        <td>
          {#if result.stored === 'data_root'}the data root{:else if result.stored === 'staging'}<strong style="color:var(--warn)">local staging</strong> (moving to the data root failed; the files are safe here){:else}{result.stored}{/if}
        </td>
      </tr>
      <tr><td class="muted">folder</td><td class="mono wrap" style="user-select:all">{result.path}</td></tr>
      <tr><td class="muted">labels</td><td class="mono">{result.n_labels}</td></tr>
      <tr>
        <td class="muted">validation</td>
        <td>
          {#if result.validation}
            <span class="chip {result.validation.ok ? 'ok' : 'err'}">{result.validation.ok ? 'sidecars valid' : 'failed'}</span>
          {:else}
            <span class="muted">not run</span>
          {/if}
        </td>
      </tr>
      <tr>
        <td class="muted">repository data/</td>
        <td>
          {#if result.sidecars_copied && result.sidecars_copied.length > 0}
            {#each result.sidecars_copied as p (p)}<div class="mono wrap">{p}</div>{/each}
          {:else}
            <span class="muted">not copied{result.sidecars_copy_skipped ? `: ${result.sidecars_copy_skipped}` : ''}</span>
          {/if}
        </td>
      </tr>
    </tbody>
  </table>

  <div style="overflow-x:auto; margin-top:10px">
    <table>
      <thead>
        <tr>
          <th>stream</th>
          <th>files</th>
          <th class="r">frames</th>
          <th class="r">duration</th>
          <th class="r">rate Hz</th>
          <th>source</th>
          <th class="r">loss dev / link / host</th>
          <th class="r">labels</th>
          <th></th>
        </tr>
      </thead>
      <tbody class="mono">
        {#each result.streams as s (s.stream)}
          <tr>
            <td>{s.stream}</td>
            <td class="wrap">{s.wav}<br />{s.sidecar}</td>
            <td class="r">{fmtInt(s.frames)}</td>
            <td class="r">{fmtFixed(s.duration_s, 1, ' s')}</td>
            <td class="r" title="measured {s.sample_rate_measured ?? '—'}">{s.sample_rate}</td>
            <td>{s.rate_source}</td>
            <td class="r">
              <span class:lossbad={s.loss.device > 0}>{fmtInt(s.loss.device)}</span> /
              <span class:lossbad={s.loss.link > 0}>{fmtInt(s.loss.link)}</span> /
              <span class:lossbad={s.loss.host > 0}>{fmtInt(s.loss.host)}</span>
            </td>
            <td class="r">{s.labels}</td>
            <td>{#if s.incomplete}<span class="chip err">incomplete</span>{/if}</td>
          </tr>
          {#each s.problems as p, i (i)}
            <tr><td></td><td colspan="8" style="color:var(--err)">{p}</td></tr>
          {/each}
        {/each}
      </tbody>
    </table>
  </div>

  {#if result.validation && result.validation.problems.length > 0}
    <div class="inline-err" role="alert" style="flex-direction:column; align-items:flex-start">
      <strong>Validation problems</strong>
      {#each result.validation.problems as p, i (i)}<div class="mono wrap">{p}</div>{/each}
    </div>
  {/if}
  {#if result.problems.length > 0}
    <div class="inline-err" role="alert" style="flex-direction:column; align-items:flex-start">
      <strong>Problems</strong>
      {#each result.problems as p, i (i)}<div class="wrap">{p}</div>{/each}
    </div>
  {/if}
  {#if result.ok}<div class="okbox" style="margin-top:8px">All files written, validated and stored.</div>{/if}
</section>
