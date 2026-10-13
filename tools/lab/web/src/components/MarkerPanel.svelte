<script lang="ts">
  // Phone marker (WEB_API.md 9.6): the URL and QR code of the LAN listener, only while a recording runs.
  import { api, ApiError } from '../lib/api';
  import { app } from '../lib/store.svelte';
  import type { MarkerInfo } from '../lib/types';

  let info = $state.raw<MarkerInfo | null>(null);
  let err = $state('');

  const rec = $derived(app.recording);
  const active = $derived(rec?.state === 'recording' && rec.marker?.active === true);
  // Reload when the listener changes (a new session or port); not on every progress event.
  const key = $derived(active ? `${rec?.session}:${rec?.marker?.port}` : '');

  $effect(() => {
    const k = key;
    info = null;
    err = '';
    if (!k) return;
    let gone = false;
    api
      .marker()
      .then((r) => {
        if (!gone) info = r;
      })
      .catch((e: unknown) => {
        if (!gone) err = e instanceof ApiError ? e.message : String(e);
      });
    return () => {
      gone = true;
    };
  });

  async function copy(url: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(url);
      app.toast('Link copied.', 'info');
    } catch {
      app.toast('Could not copy; select the link and copy it by hand.', 'error');
    }
  }
</script>

<section class="card">
  <header><h2>Phone marker</h2></header>
  {#if rec?.state !== 'recording'}
    <div class="empty">The QR code appears here while a recording runs (if the form asked for the phone marker).</div>
  {:else if !rec.marker}
    {#if rec.marker_error}
      <div class="inline-err" role="alert">The phone marker could not start: {rec.marker_error} The recording runs anyway; use Space.</div>
    {:else}
      <div class="muted">No phone marker for this recording (it was switched off in the form).</div>
    {/if}
  {:else if err}
    <div class="inline-err" role="alert">{err}</div>
  {:else if !info}
    <div class="empty">Loading…</div>
  {:else if !info.active}
    <div class="muted">{info.reason}</div>
  {:else}
    <div class="row" style="align-items:flex-start; gap:18px">
      <div class="qr" aria-label="QR code of the phone marker link">
        <!-- qr_svg comes from this lab server's loopback API (a complete <svg> element) -->
        {@html info.qr_svg}
      </div>
      <div class="stack" style="flex:1; min-width:220px; gap:8px">
        <div>Scan with the phone, or open this link on it:</div>
        <div class="mono wrap" style="user-select:all">{info.url}</div>
        <div><button onclick={() => copy(info?.active ? info.url : '')}>Copy link</button></div>
        <div class="muted">
          The phone must be on the <strong>same network</strong> as this PC (<span class="mono">{info.host}</span>), not a guest
          Wi-Fi. If it cannot connect, allow python.exe on private networks in the Windows firewall. The link works only for
          this recording. Label and person of phone marks come from the label form on this page.
        </div>
      </div>
    </div>
  {/if}
</section>
