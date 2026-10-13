<script lang="ts">
  import { tick } from 'svelte';
  import { app } from '../lib/store.svelte';
  import { fmtClock } from '../lib/format';

  const LEVELS: [number, string][] = [
    [1, 'error'],
    [2, 'warn and above'],
    [3, 'info and above'],
    [4, 'debug and above'],
    [5, 'everything'],
  ];
  const MAX_SHOWN = 400;

  let level = $state(3);
  let autoscroll = $state(true);
  let box: HTMLDivElement | undefined = $state();

  const shown = $derived.by(() => {
    const out = app.logs.filter((l) => l.level <= level);
    return out.length > MAX_SHOWN ? out.slice(out.length - MAX_SHOWN) : out;
  });

  $effect(() => {
    void shown;
    if (autoscroll && box) {
      const b = box;
      void tick().then(() => {
        b.scrollTop = b.scrollHeight;
      });
    }
  });

  function onScroll(): void {
    if (!box) return;
    const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 24;
    if (!atBottom && autoscroll) autoscroll = false;
  }
</script>

<section class="card">
  <header>
    <h2>Device log</h2>
    <span class="muted num">{shown.length} of {app.logs.length} lines</span>
    <span class="grow"></span>
    <label class="muted" style="display:flex; gap:6px; align-items:center">
      Level
      <select bind:value={level}>
        {#each LEVELS as [v, name] (v)}<option value={v}>{name}</option>{/each}
      </select>
    </label>
    <label class="muted" style="display:flex; gap:6px; align-items:center">
      <input type="checkbox" bind:checked={autoscroll} /> Autoscroll
    </label>
  </header>
  <div class="console" bind:this={box} onscroll={onScroll} role="log" aria-label="Device log">
    {#each shown as l, i (i)}
      <div class="ln lv{l.level}">
        <span class="t">{fmtClock(l.t)}</span>
        <span class="t">{l.source === 'host' ? 'host' : 'node'}/{l.tag}</span>
        [{l.level_name}] {l.msg}
      </div>
    {:else}
      <div class="muted">No log lines at this level.</div>
    {/each}
  </div>
</section>
