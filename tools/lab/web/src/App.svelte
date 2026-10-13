<script lang="ts">
  import { onMount } from 'svelte';
  import StatusStrip from './components/StatusStrip.svelte';
  import Toasts from './components/Toasts.svelte';
  import LivePage from './components/LivePage.svelte';
  import DevicePage from './components/DevicePage.svelte';
  import RecordPage from './components/RecordPage.svelte';
  import { app } from './lib/store.svelte';

  type Path = '/live' | '/device' | '/record';
  const LATER = ['Label', 'Bench', 'Experiments', 'Datasets'];

  let path = $state(normalise(location.pathname));

  function normalise(p: string): Path {
    if (p.startsWith('/device')) return '/device';
    if (p.startsWith('/record')) return '/record';
    return '/live';
  }

  function go(e: MouseEvent, to: Path): void {
    e.preventDefault();
    if (path !== to) history.pushState({}, '', to);
    path = to;
  }

  onMount(() => {
    app.init();
    const onPop = () => (path = normalise(location.pathname));
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  });
</script>

<div class="shell">
  <nav class="rail" aria-label="Pages">
    <div class="brand">
      <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden="true">
        <rect width="32" height="32" rx="6" fill="var(--panel2)" />
        <path d="M3 17h5l3-9 5 17 4-14 3 6h6" fill="none" stroke="var(--accent)" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round" />
      </svg>
      <span>Rezonating Lab</span>
    </div>
    <a href="/live" class:active={path === '/live'} onclick={(e) => go(e, '/live')} aria-current={path === '/live' ? 'page' : undefined}>Live</a>
    <a href="/device" class:active={path === '/device'} onclick={(e) => go(e, '/device')} aria-current={path === '/device' ? 'page' : undefined}>Device</a>
    <a href="/record" class:active={path === '/record'} onclick={(e) => go(e, '/record')} aria-current={path === '/record' ? 'page' : undefined}>
      Record{#if app.recActive}<span class="dot rec on" style="margin-left:8px" aria-label="recording"></span>{/if}
    </a>
    {#each LATER as name (name)}
      <span class="soon" aria-disabled="true" title="Coming in a later phase">{name}<small>coming</small></span>
    {/each}
    <span class="spacer"></span>
    <button onclick={() => app.setTheme(app.theme === 'dark' ? 'light' : 'dark')} aria-label="Toggle light and dark theme">
      Theme: {app.theme}
    </button>
  </nav>
  <div class="main">
    <StatusStrip />
    <main class="content">
      {#if path === '/live'}
        <LivePage />
      {:else if path === '/device'}
        <DevicePage />
      {:else}
        <RecordPage />
      {/if}
    </main>
  </div>
</div>
<Toasts />
