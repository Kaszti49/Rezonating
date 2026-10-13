<script lang="ts">
  // Where recordings go (WEB_API.md 9.2): the data root, its check, and PUT to set it in the user's config.toml.
  import { api, ApiError } from '../lib/api';
  import { app } from '../lib/store.svelte';
  import { fmtFixed } from '../lib/format';
  import type { DataRoot } from '../lib/types';

  let { root, onchanged }: { root: DataRoot | null; onchanged: () => void } = $props();

  let path = $state('');
  let err = $state('');
  let saving = $state(false);
  let checking = $state(false);
  let checked = $state.raw<DataRoot | null>(null);

  // A fresh check (GET data-root) wins over the copy inside the options until the options are reloaded.
  const dr = $derived(checked ?? root);
  const fromEnv = $derived(dr?.source === 'env');

  async function save(): Promise<void> {
    const p = path.trim();
    err = '';
    if (!p) {
      err = 'Type the full path of an existing folder outside the repository.';
      return;
    }
    saving = true;
    try {
      checked = await api.setDataRoot(p);
      path = '';
      app.toast('Data root saved.', 'info');
      onchanged();
    } catch (e) {
      err = e instanceof ApiError ? e.message : String(e);
    } finally {
      saving = false;
    }
  }

  async function recheck(): Promise<void> {
    checking = true;
    err = '';
    try {
      checked = await api.dataRoot();
      onchanged();
    } catch (e) {
      err = e instanceof ApiError ? e.message : String(e);
    } finally {
      checking = false;
    }
  }

  $effect(() => {
    // New options arrived: drop the older fresh check.
    void root;
    checked = null;
  });
</script>

<section class="card">
  <header>
    <h2>Where recordings go</h2>
    <span class="grow"></span>
    {#if dr}
      <span class="chip {dr.ok ? 'ok' : 'err'}">{dr.ok ? 'data root ok' : 'not usable'}</span>
    {/if}
    <button onclick={recheck} disabled={checking}>{checking ? 'Checking…' : 'Check again'}</button>
  </header>

  {#if !dr}
    <div class="empty">Loading…</div>
  {:else}
    <table>
      <tbody>
        <tr><td class="muted" style="width:9em">data root</td><td class="mono wrap">{dr.path ?? 'not set'}</td></tr>
        <tr>
          <td class="muted">set by</td>
          <td>
            {#if dr.source === 'env'}the <span class="mono">RZ_DATA_ROOT</span> environment variable{:else if dr.source === 'config'}the config file{:else}nothing yet{/if}
            {#if dr.config_file}<span class="muted"> · config: <span class="mono wrap">{dr.config_file}</span></span>{/if}
          </td>
        </tr>
        {#if dr.ok}<tr><td class="muted">free space</td><td class="mono">{fmtFixed(dr.free_gb, 1, ' GB')}</td></tr>{/if}
      </tbody>
    </table>
    {#if dr.error}
      <div class="inline-err" role="alert"><strong class="mono">{dr.error.code}</strong><span>{dr.error.message}</span></div>
    {/if}

    {#if fromEnv}
      <div class="muted" style="margin-top:8px">
        Set by <span class="mono">RZ_DATA_ROOT</span>, which wins over the config file: change the variable and restart <span class="mono">rzlab serve</span> to move it.
      </div>
    {:else}
      <form
        class="row"
        style="margin-top:10px"
        onsubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <label class="field" style="flex:1; min-width:240px">
          <span>{dr.configured ? 'Change the data root' : 'Set the data root'}: full path of an existing folder, outside the git repository (e.g. the shared drive)</span>
          <input class="mono" bind:value={path} placeholder="D:\rezonating-recordings" autocomplete="off" disabled={app.recActive} />
        </label>
        <button class="primary" type="submit" disabled={saving || app.recActive || !path.trim()}>{saving ? 'Saving…' : 'Save to config'}</button>
      </form>
      {#if app.recActive}<div class="muted" style="margin-top:4px">The data root cannot change while a recording runs.</div>{/if}
    {/if}
    {#if err}<div class="inline-err" role="alert">{err}</div>{/if}
  {/if}
</section>
