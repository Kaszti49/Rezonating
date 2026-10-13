<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type ConnectRequest } from '../lib/api';
  import { app } from '../lib/store.svelte';
  import type { PortInfo } from '../lib/types';

  let ports = $state<PortInfo[]>([]);
  let portsErr = $state('');
  let selPort = $state('');
  let serialUrl = $state('');
  let host = $state('');
  let tcpPort = $state(7350);
  let key = $state('');
  let connectErr = $state('');

  const keyOk = $derived(key.trim() === '' || /^[0-9a-fA-F]{32}$/.test(key.trim()));
  const connState = $derived(app.connection?.state ?? 'disconnected');
  const working = $derived(app.busy === 'connect' || app.busy === 'disconnect' || connState === 'connecting' || connState === 'disconnecting');
  const isUp = $derived(connState === 'connected' || connState === 'connecting');

  async function refresh(): Promise<void> {
    try {
      const r = await api.ports();
      ports = r.ports;
      portsErr = '';
      if (!selPort || !ports.some((p) => p.device === selPort)) {
        selPort = ports.find((p) => p.is_node)?.device ?? '';
        serialUrl = selPort;
      }
    } catch (e) {
      portsErr = e instanceof Error ? e.message : String(e);
    }
  }

  function choose(dev: string): void {
    selPort = dev;
    serialUrl = dev;
  }

  async function go(req: ConnectRequest): Promise<void> {
    connectErr = '';
    if (!keyOk) {
      connectErr = 'The pairing key must be 32 hex digits.';
      return;
    }
    const k = key.trim();
    if (k) req.key = k;
    const err = await app.run('connect', () => api.connect(req), true);
    if (err) connectErr = err.message;
  }

  async function disconnect(): Promise<void> {
    connectErr = '';
    await app.disconnect();
  }

  onMount(() => void refresh());
</script>

<section class="card">
  <header>
    <h2>Connect</h2>
    <span class="grow"></span>
    <span class="chip {connState === 'connected' ? 'ok' : connState === 'disconnected' ? '' : 'warn'}">{connState}</span>
    {#if app.connection?.target}<span class="mono muted">{app.connection.link} {app.connection.target}</span>{/if}
    <button class="danger" onclick={disconnect} disabled={!isUp || app.busy !== null}>Disconnect</button>
  </header>

  <div class="grid2" style="gap:18px">
    <div>
      <div class="row" style="justify-content:space-between; margin-bottom:6px">
        <strong>Serial (USB)</strong>
        <button onclick={refresh}>Refresh ports</button>
      </div>
      {#if portsErr}<div class="inline-err">{portsErr}</div>{/if}
      {#if ports.length === 0 && !portsErr}<div class="muted">No serial ports found.</div>{/if}
      <div role="radiogroup" aria-label="Serial ports" style="display:flex; flex-direction:column; gap:3px; max-height:150px; overflow-y:auto">
        {#each ports as p (p.device)}
          <label style="display:flex; gap:8px; align-items:center">
            <input type="radio" name="port" value={p.device} checked={selPort === p.device} onchange={() => choose(p.device)} />
            <span class="mono">{p.device}</span>
            <span class="muted" style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap">{p.description}</span>
            {#if p.vid_pid}<span class="chip mono {p.is_node ? 'ok' : ''}">{p.vid_pid}</span>{/if}
            {#if p.is_node}<span class="chip ok">node</span>{/if}
          </label>
        {/each}
      </div>
      <div class="row" style="margin-top:8px">
        <label class="field" style="flex:1; min-width:180px">
          <span>Port or URL (COM5, /dev/ttyACM0, socket://host:port)</span>
          <input class="mono" bind:value={serialUrl} placeholder="COM5" />
        </label>
        <button class="primary" disabled={working || !serialUrl.trim()} onclick={() => go({ kind: 'serial', url: serialUrl.trim() })}>
          Connect serial
        </button>
      </div>
    </div>

    <div>
      <strong>TCP (Wi-Fi node)</strong>
      <div class="row" style="margin-top:6px">
        <label class="field" style="flex:1; min-width:150px">
          <span>Host</span>
          <input class="mono" bind:value={host} placeholder="192.168.x.x" />
        </label>
        <label class="field" style="width:90px">
          <span>Port</span>
          <input class="mono" type="number" min="1" max="65535" bind:value={tcpPort} />
        </label>
        <button class="primary" disabled={working || !host.trim()} onclick={() => go({ kind: 'tcp', host: host.trim(), port: tcpPort })}>
          Connect TCP
        </button>
      </div>
      <div class="row" style="margin-top:12px">
        <label class="field" style="flex:1; min-width:220px">
          <span>Pairing key (optional, 32 hex digits)</span>
          <input class="mono" bind:value={key} placeholder="needed for Wi-Fi nodes" autocomplete="off" aria-invalid={!keyOk} />
        </label>
        <button disabled={working} onclick={() => go({ kind: 'sim' })}>Simulator</button>
      </div>
      {#if !keyOk}<div class="muted" style="color:var(--warn); margin-top:4px">Key must be exactly 32 hex digits.</div>{/if}
      {#if app.connection?.embedded_sim}<div class="muted" style="margin-top:4px">Using the simulator embedded in the server.</div>{/if}
    </div>
  </div>

  {#if working}<div class="muted" style="margin-top:8px">Working&hellip; a connect can take up to 5 s.</div>{/if}
  {#if connectErr}<div class="inline-err">{connectErr}</div>{/if}
</section>
