<script lang="ts">
  // Logged results only (GET /api/home/results reads the experiment notes): the newest side test as bars, and the
  // headline of the other finished experiments. In-sample results say so.
  import { onMount } from 'svelte';
  import { Tween } from 'svelte/motion';
  import { cubicOut } from 'svelte/easing';
  import Counter from './Counter.svelte';
  import { homeApi, reducedMotion, type ExperimentResult } from '../../lib/home';

  let all = $state.raw<ExperimentResult[] | null>(null);
  let failed = $state(false);
  let table = $state(false);
  const grow = new Tween(0, { duration: reducedMotion() ? 0 : 1200, easing: cubicOut });

  const test = $derived(all ? [...all].reverse().find((e) => e.status === 'done' && e.score.length > 0) ?? null : null);
  const others = $derived(all ? [...all].reverse().filter((e) => e.status === 'done' && e.score.length > 0 && e.pack !== test?.pack) : []);
  const sum = $derived.by(() => {
    const s = { right: 0, same: 0, wrong: 0, n: 0 };
    for (const r of test?.score ?? []) {
      s.right += r.right;
      s.same += r.same;
      s.wrong += r.wrong;
      s.n += r.right + r.same + r.wrong;
    }
    return s;
  });

  onMount(() => {
    void homeApi
      .results()
      .then((r) => {
        all = r.experiments;
        void grow.set(1);
      })
      .catch(() => {
        failed = true;
      });
  });

  const pct = (v: number, n: number): string => `${n > 0 ? (100 * v * grow.current) / n : 0}%`;
</script>

{#if failed}
  <p class="muted small">The results could not be read.</p>
{:else if all === null}
  <div class="skel" style="height:100%" aria-hidden="true"></div>
{:else if !test}
  <p class="muted small">No side test is logged yet.</p>
{:else}
  <div class="res">
    <div class="head">
      <div class="big"><Counter value={sum.right} /><span class="of"> of {sum.n}</span></div>
      <div class="cap">
        steps given the correct side
        <span class="muted">{test.id} · {test.date}{test.people ? ` · ${test.people} ${test.people === 1 ? 'person' : 'people'}` : ''}</span>
      </div>
      <button class="link" onclick={() => (table = !table)} aria-pressed={table}>{table ? 'Chart' : 'Table'}</button>
    </div>
    {#if table}
      <table>
        <thead><tr><th>Steps</th><th>Correct</th><th>No side</th><th>Wrong</th></tr></thead>
        <tbody>
          {#each test.score as r (r.set)}
            <tr><td>{r.set}</td><td>{r.right}</td><td>{r.same}</td><td>{r.wrong}</td></tr>
          {/each}
        </tbody>
      </table>
    {:else}
      <div class="bars">
        {#each test.score as r (r.set)}
          {@const n = r.right + r.same + r.wrong}
          <div class="row" title={`${r.set}: ${r.right} correct, ${r.same} no side, ${r.wrong} wrong`}>
            <span class="name">{r.set}</span>
            <span class="track">
              {#if r.right}<i class="right" style:width={pct(r.right, n)}></i>{/if}
              {#if r.same}<i class="same" style:width={pct(r.same, n)}></i>{/if}
              {#if r.wrong}<i class="wrong" style:width={pct(r.wrong, n)}></i>{/if}
            </span>
            <span class="num">{r.right}/{n}</span>
          </div>
        {/each}
      </div>
    {/if}
    <div class="foot">
      <span class="key"><i class="right"></i>correct</span>
      <span class="key"><i class="same"></i>no side given</span>
      <span class="key"><i class="wrong"></i>wrong</span>
      {#if test.in_sample}<span class="note">Early result: the limits were chosen on these steps</span>{/if}
    </div>
    {#if others.length}
      <div class="others">
        {#each others as e (e.id)}
          <span><b><Counter value={e.score.reduce((s, r) => s + r.right, 0)} /> of {e.score.reduce((s, r) => s + r.right + r.same + r.wrong, 0)}</b> {e.title} <span class="muted">{e.id}, {e.date}</span></span>
        {/each}
      </div>
    {/if}
  </div>
{/if}

<style>
  .res {
    display: flex;
    flex-direction: column;
    gap: 8px;
    height: 100%;
    min-height: 0;
  }
  .head {
    display: flex;
    align-items: baseline;
    gap: 12px;
  }
  .big {
    font-size: 34px;
    font-weight: 700;
    line-height: 1;
    white-space: nowrap;
  }
  .of {
    font-size: 17px;
    font-weight: 500;
    color: var(--muted);
    margin-left: 6px;
  }
  .cap {
    flex: 1;
    font-size: 12.5px;
    line-height: 1.25;
  }
  .cap .muted {
    display: block;
    font-size: 11px;
  }
  .link {
    background: none;
    border: 0;
    color: var(--muted);
    font-size: 11.5px;
    padding: 2px 4px;
  }
  .bars {
    display: flex;
    flex-direction: column;
    gap: 7px;
  }
  .row {
    display: grid;
    grid-template-columns: 128px minmax(0, 1fr) 34px;
    gap: 10px;
    align-items: center;
    font-size: 11.5px;
  }
  .name {
    color: var(--muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .track {
    display: flex;
    gap: 2px;
    height: 12px;
  }
  .track i {
    display: block;
    height: 100%;
    min-width: 2px;
  }
  .track i:last-child {
    border-radius: 0 4px 4px 0;
  }
  i.right {
    background: var(--good);
  }
  i.same {
    background: var(--side-none);
  }
  i.wrong {
    background: var(--bad);
  }
  .num {
    text-align: right;
  }
  .foot {
    display: flex;
    flex-wrap: wrap;
    gap: 2px 12px;
    font-size: 11px;
    color: var(--muted);
    align-items: center;
  }
  .key {
    display: inline-flex;
    gap: 5px;
    align-items: center;
  }
  .key i {
    width: 9px;
    height: 9px;
    border-radius: 2px;
  }
  .note {
    margin-left: auto;
  }
  .others {
    margin-top: auto;
    border-top: 1px solid var(--line);
    padding-top: 7px;
    font-size: 12px;
    display: flex;
    flex-wrap: wrap;
    gap: 3px 18px;
  }
  table {
    border-collapse: collapse;
    font-size: 12px;
    width: 100%;
  }
  th,
  td {
    text-align: right;
    padding: 2px 6px;
    font-variant-numeric: tabular-nums;
  }
  th {
    color: var(--muted);
    font-weight: 500;
  }
  th:first-child,
  td:first-child {
    text-align: left;
  }
  .small {
    font-size: 12.5px;
  }
  @container results (max-height: 200px) {
    .res {
      gap: 5px;
    }
    .big {
      font-size: 24px;
    }
    .bars {
      gap: 3px;
    }
    .track {
      height: 10px;
    }
    .others {
      padding-top: 4px;
    }
  }
</style>
