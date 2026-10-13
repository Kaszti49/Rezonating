<script lang="ts">
  import { onMount } from 'svelte';
  import StatusStrip from './components/StatusStrip.svelte';
  import Toasts from './components/Toasts.svelte';
  import LivePage from './components/LivePage.svelte';
  import DevicePage from './components/DevicePage.svelte';
  import RecordPage from './components/RecordPage.svelte';
  import ReviewPage from './components/ReviewPage.svelte';
  import DatasetsPage from './components/DatasetsPage.svelte';
  import ExperimentsPage from './components/ExperimentsPage.svelte';
  import BenchPage from './components/BenchPage.svelte';
  import { app } from './lib/store.svelte';

  type Path = '/live' | '/device' | '/record' | '/review' | '/datasets' | '/experiments' | '/bench';
  const LATER: string[] = [];

  let path = $state(normalise(location.pathname));

  function normalise(p: string): Path {
    if (p.startsWith('/device')) return '/device';
    if (p.startsWith('/record')) return '/record';
    if (p.startsWith('/review')) return '/review';
    if (p.startsWith('/datasets')) return '/datasets';
    if (p.startsWith('/bench')) return '/bench';
    if (p.startsWith('/experiments')) return '/experiments';
    return '/live';
  }

  const LEAVE_REVIEW = 'The Review page has unsaved label changes. Leave the page and lose them?';

  /** Leaving the Review page with unsaved edits needs a yes (the page's own state is lost when it unmounts). */
  function mayLeave(to: Path): boolean {
    if (path !== '/review' || to === '/review' || !app.reviewDirty) return true;
    if (!confirm(LEAVE_REVIEW)) return false;
    app.reviewDirty = false;
    return true;
  }

  function go(e: MouseEvent, to: Path): void {
    e.preventDefault();
    if (!mayLeave(to)) return;
    if (path !== to) history.pushState({}, '', to);
    path = to;
    here = location.pathname + location.search;
  }

  /** The URL of the page shown (with its ?session=), so a refused Back can return to it exactly. */
  let here = location.pathname + location.search;

  /** Datasets -> Review with that session opened (ReviewPage reads `?session=` when it mounts). */
  function openInReview(session: string): void {
    history.pushState({}, '', `/review?session=${encodeURIComponent(session)}`);
    path = '/review';
    here = location.pathname + location.search;
  }

  onMount(() => {
    app.init();
    const onPop = () => {
      const to = normalise(location.pathname);
      if (!mayLeave(to)) {
        history.pushState({}, '', here); // Back was refused: stay on Review, with its own ?session=
        return;
      }
      path = to;
      here = location.pathname + location.search;
    };
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
    <a href="/review" class:active={path === '/review'} onclick={(e) => go(e, '/review')} aria-current={path === '/review' ? 'page' : undefined}>Review</a>
    <a href="/datasets" class:active={path === '/datasets'} onclick={(e) => go(e, '/datasets')} aria-current={path === '/datasets' ? 'page' : undefined}>Datasets</a>
    <a href="/experiments" class:active={path === '/experiments'} onclick={(e) => go(e, '/experiments')} aria-current={path === '/experiments' ? 'page' : undefined}>Experiments</a>
    <a href="/bench" class:active={path === '/bench'} onclick={(e) => go(e, '/bench')} aria-current={path === '/bench' ? 'page' : undefined}>Bench</a>
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
      {:else if path === '/review'}
        <ReviewPage />
      {:else if path === '/bench'}
        <BenchPage />
      {:else if path === '/datasets'}
        <DatasetsPage onOpenReview={openInReview} />
      {:else if path === '/experiments'}
        <ExperimentsPage />
      {:else}
        <RecordPage />
      {/if}
    </main>
  </div>
</div>
<Toasts />
