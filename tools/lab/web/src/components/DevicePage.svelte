<script lang="ts">
  import ConnectPanel from './ConnectPanel.svelte';
  import NodeInfo from './NodeInfo.svelte';
  import MiniGraph from './MiniGraph.svelte';
  import LogConsole from './LogConsole.svelte';
  import { app } from '../lib/store.svelte';
  import { fmtBytes, fmtFixed } from '../lib/format';

  const SCOL = ['--s0', '--s1', '--s2'];
  const SFALL = ['#e2e8f0', '#2dd4bf', '#f472b6'];

  const streams = $derived(app.hello?.streams ?? []);
  const rateSeries = $derived(
    streams.map((s, i) => ({ label: s.name, cssVar: SCOL[i % 3], fallback: SFALL[i % 3] })),
  );
  const rateIds = $derived(streams.map((s) => s.id));
  const link = $derived(app.status?.link ?? null);
  const health = $derived(app.status?.health ?? null);

  const lossSeries = [
    { label: 'device', cssVar: '--err', fallback: '#f87171' },
    { label: 'link', cssVar: '--warn', fallback: '#fbbf24' },
    { label: 'host', cssVar: '--s1', fallback: '#2dd4bf' },
  ];
</script>

<ConnectPanel />

<div class="grid2">
  <NodeInfo />
  <section class="card">
    <header><h2>Link and health</h2></header>
    {#if !app.status}
      <div class="empty">Waiting for the first status event.</div>
    {:else}
      <table>
        <tbody class="mono">
          <tr><td class="muted">link</td><td>{link?.type ?? '—'} {link?.target ?? ''}</td></tr>
          <tr><td class="muted">round trip</td><td>{fmtFixed(link?.rtt_ms, 2, ' ms')}</td></tr>
          <tr><td class="muted">bad / lost frames</td><td>{link?.bad_frames ?? '—'} / {link?.lost_frames ?? '—'}</td></tr>
          <tr><td class="muted">receive rate</td><td>{fmtBytes(link?.rx_bytes_per_s)}/s</td></tr>
          <tr><td class="muted">queue fill</td><td>{fmtFixed(health?.queue_fill, 0, ' %')}</td></tr>
          <tr><td class="muted">heap free</td><td>{fmtBytes(health?.heap_free)}</td></tr>
          <tr><td class="muted">temperature</td><td>{fmtFixed(health?.temp_c, 1, ' °C')}</td></tr>
          <tr><td class="muted">Wi-Fi RSSI</td><td>{fmtFixed(health?.rssi_dbm, 0, ' dBm')}</td></tr>
          <tr><td class="muted">SD card</td><td>{['none', 'ready', 'recording', 'error'][health?.sd_state ?? -1] ?? '—'}</td></tr>
        </tbody>
      </table>
    {/if}
  </section>
</div>

{#key app.hello?.node_id}
  <div class="grid3">
    <MiniGraph
      title="Measured rate"
      yLabel="Hz"
      series={rateSeries}
      pick={() => rateIds.map((id) => app.health.rate.get(id) ?? [])}
      digits={1}
    />
    <MiniGraph
      title="Lost samples (all streams)"
      yLabel="samples"
      series={lossSeries}
      pick={() => [app.health.lossDevice, app.health.lossLink, app.health.lossHost]}
      digits={0}
    />
    <MiniGraph
      title="Node queue fill"
      yLabel="%"
      series={[{ label: 'queue', cssVar: '--s0', fallback: '#e2e8f0' }]}
      pick={() => [app.health.queue]}
      digits={0}
    />
    <MiniGraph
      title="Heap free"
      yLabel="kB"
      series={[{ label: 'heap', cssVar: '--s1', fallback: '#2dd4bf' }]}
      pick={() => [app.health.heap]}
      digits={0}
    />
    <MiniGraph
      title="Temperature"
      yLabel="deg C"
      series={[{ label: 'temp', cssVar: '--warn', fallback: '#fbbf24' }]}
      pick={() => [app.health.temp]}
      digits={1}
    />
    <MiniGraph
      title="Wi-Fi RSSI"
      yLabel="dBm"
      series={[{ label: 'rssi', cssVar: '--s2', fallback: '#f472b6' }]}
      pick={() => [app.health.rssi]}
      digits={0}
    />
  </div>
{/key}

<LogConsole />
