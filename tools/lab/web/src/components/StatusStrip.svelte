<script lang="ts">
  import { app } from '../lib/store.svelte';
  import { fmtElapsed, fmtFixed, fmtHostLoss, fmtInt, fmtPct } from '../lib/format';

  const conn = $derived(app.connection);
  const rec = $derived(app.recording);
  // The recording event is the source; status.recording covers the moment before the first one arrives.
  const recOn = $derived(app.recActive || (rec == null && app.status?.recording === true));
  const st = $derived(app.status);
  const node = $derived(st?.node ?? (app.hello ? { node_id: app.hello.node_id, fw_version: app.hello.fw_version } : null));
  const connState = $derived(conn?.state ?? 'disconnected');
  const dotClass = $derived(
    app.ws !== 'open'
      ? 'err'
      : connState === 'connected'
        ? st?.link?.stale
          ? 'warn'
          : 'ok'
        : connState === 'disconnected'
          ? ''
          : 'warn',
  );
</script>

<div class="strip" role="status" aria-label="Connection and stream status">
  <div class="grp">
    <span class="dot {dotClass}"></span>
    <span class="k">node</span>
    <span class="mono">{node?.node_id ?? '—'}</span>
    <span class="k">fw</span>
    <span class="mono">{node?.fw_version ?? '—'}</span>
  </div>
  <div class="grp">
    <span class="k">link</span>
    <span class="mono">{conn?.link ?? '—'}</span>
    <span class="chip {connState === 'connected' ? 'ok' : connState === 'disconnected' ? '' : 'warn'}">{connState}</span>
    {#if st?.link?.stale}<span class="chip warn">stale</span>{/if}
    {#if st?.link?.rtt_ms != null}<span class="mono muted">{fmtFixed(st.link.rtt_ms, 1)} ms</span>{/if}
  </div>
  {#if app.ws !== 'open'}
    <div class="grp">
      <span class="chip err">
        {app.ws === 'connecting' ? 'connecting to server' : `server link down, retry ${app.wsAttempt}`}
      </span>
    </div>
  {/if}
  {#if conn?.error && connState === 'disconnected'}
    <div class="grp"><span class="chip err" title={conn.error}>{conn.error}</span></div>
  {/if}

  {#each st?.streams ?? [] as s (s.id)}
    {@const l = s.loss}
    <div class="grp" class:stale={app.ws !== 'open'} title="Loss counters: device = lost on the node, link = lost between node and server, host = sent but never arrived">
      <span class="sep">|</span>
      <strong class="mono">{s.name}</strong>
      {#if s.running}
        <span class="mono">{fmtFixed(s.rate_hz_fit ?? s.rate_hz_status, 1, ' Hz')}</span>
        <span class="mono muted">{fmtPct(s.offset_pct_fit ?? s.offset_pct_status)}</span>
      {:else}
        <span class="muted">idle</span>
      {/if}
      {#if l}
        <span class="k">loss</span>
        <span class="mono" class:lossbad={l.device > 0}>dev {fmtInt(l.device)}</span>
        <span class="mono" class:lossbad={l.link > 0}>link {fmtInt(l.link)}</span>
        <span class="mono" class:lossbad={l.host > 0}>host {fmtHostLoss(l.host, l.host_exact)}</span>
        {#if l.protocol_bug}<span class="chip err">protocol bug</span>{/if}
        {#if l.incomplete}<span class="chip warn">incomplete</span>{/if}
      {/if}
    </div>
  {/each}

  <div
    class="grp"
    style="margin-left:auto"
    title={recOn ? `Recording ${rec?.session ?? ''}` : 'Not recording (Record page)'}
  >
    <span class="dot rec" class:on={recOn}></span><span class="k" class:recon={recOn}>REC</span>
    {#if recOn}
      {#if rec?.state && rec.state !== 'recording'}<span class="chip warn">{rec.state}</span>{/if}
      <span class="mono">{fmtElapsed(rec?.elapsed_s)}</span>
    {/if}
  </div>
</div>
