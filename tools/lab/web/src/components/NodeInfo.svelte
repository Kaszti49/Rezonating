<script lang="ts">
  import { app } from '../lib/store.svelte';
  import { fmtInt } from '../lib/format';

  const GAINS = [1, 2, 4, 8, 16, 32, 64, 128];
  const RANGES = [2, 4, 8];

  const hello = $derived(app.hello);
  const adc = $derived(app.config?.streams.find((s) => s.name === 'adc_raw') ?? app.config?.streams[0]);
  const hasAccel = $derived(app.config?.streams.some((s) => s.name === 'accel') ?? false);
  const acquiring = $derived(app.status?.acquiring ?? false);

  /** One inline error per setting key. */
  let errs = $state<Record<string, { code: string; message: string; value: number }>>({});

  async function apply(key: string, value: number, el: HTMLSelectElement, current: number): Promise<void> {
    const err = await app.setValue(key, value);
    if (err) {
      errs = { ...errs, [key]: { code: err.code, message: err.message, value } };
      el.value = String(current); // the node kept the old value
    } else {
      const { [key]: _gone, ...rest } = errs;
      errs = rest;
    }
  }

  async function stopAndRetry(key: string): Promise<void> {
    const e = errs[key];
    if (!e) return;
    const stopErr = await app.stopAcq();
    if (stopErr) return;
    const err = await app.setValue(key, e.value);
    if (err) errs = { ...errs, [key]: { code: err.code, message: err.message, value: e.value } };
    else {
      const { [key]: _gone, ...rest } = errs;
      errs = rest;
    }
  }
</script>

<section class="card">
  <header><h2>Node</h2><span class="grow"></span></header>
  {#if !hello}
    <div class="empty">No node connected.</div>
  {:else}
    <div class="row" style="gap:24px; margin-bottom:10px">
      <div><span class="muted">node id</span><br /><span class="mono">{hello.node_id}</span></div>
      <div><span class="muted">firmware</span><br /><span class="mono">{hello.fw_version}</span></div>
      <div><span class="muted">protocol</span><br /><span class="mono">v{hello.proto}</span></div>
    </div>
    <table>
      <thead>
        <tr><th>id</th><th>stream</th><th class="r">ch</th><th class="r">nominal</th><th class="r">bits</th><th>clock</th><th class="r">FIR taps</th></tr>
      </thead>
      <tbody class="mono">
        {#each hello.streams as s (s.id)}
          <tr>
            <td>{s.id}</td><td>{s.name}</td><td class="r">{s.n_ch}</td><td class="r">{fmtInt(s.nominal_hz)} Hz</td>
            <td class="r">{s.bits}</td><td>{s.clock}</td><td class="r">{s.fir_taps}</td>
          </tr>
        {/each}
      </tbody>
    </table>

    <h2 style="margin-top:14px">Heads</h2>
    {#if hello.heads.length === 0}
      <div class="muted">No head descriptors reported.</div>
    {:else}
      {#each hello.heads as h (h.port)}
        <details style="margin-top:4px">
          <summary>Port {h.port}{h.descriptor == null ? ' (descriptor unreadable)' : ''}</summary>
          {#if h.descriptor != null}<pre class="mono" style="margin:6px 0; overflow-x:auto">{JSON.stringify(h.descriptor, null, 2)}</pre>{/if}
        </details>
      {/each}
    {/if}

    <h2 style="margin-top:14px">Gain and range</h2>
    <div class="muted" style="margin-bottom:6px">Changes are only allowed while the sensor is idle.</div>
    <div class="row">
      {#if adc}
        {#each adc.channels as ch, i (i)}
          {@const key = `adc.gain.${i}`}
          <label class="field">
            <span>ADC ch{i} gain</span>
            <select
              value={ch.gain}
              disabled={app.busy !== null}
              onchange={(e) => apply(key, Number(e.currentTarget.value), e.currentTarget, ch.gain)}
            >
              {#each GAINS as g (g)}<option value={g}>x{g}</option>{/each}
            </select>
          </label>
        {/each}
      {/if}
      {#if hasAccel && app.config}
        {@const cur = app.config.accel_range_g}
        <label class="field">
          <span>Accel range</span>
          <select
            value={cur}
            disabled={app.busy !== null}
            onchange={(e) => apply('accel.range_g', Number(e.currentTarget.value), e.currentTarget, cur)}
          >
            {#each RANGES as r (r)}<option value={r}>&plusmn;{r} g</option>{/each}
          </select>
        </label>
      {/if}
    </div>
    {#each Object.entries(errs) as [key, e] (key)}
      <div class="inline-err" role="alert">
        <span><strong class="mono">{key}</strong>: {e.message}</span>
        {#if e.code === 'busy' && acquiring}
          <button onclick={() => stopAndRetry(key)} disabled={app.busy !== null}>Stop acquisition and apply</button>
        {/if}
        <button onclick={() => { const { [key]: _g, ...rest } = errs; errs = rest; }} aria-label="Dismiss">&times;</button>
      </div>
    {/each}
  {/if}
</section>
