<script lang="ts">
  import { onMount } from 'svelte';
  import StatusStrip from './components/StatusStrip.svelte';
  import Toasts from './components/Toasts.svelte';
  import HomePage from './components/HomePage.svelte';
  import LivePage from './components/LivePage.svelte';
  import DevicePage from './components/DevicePage.svelte';
  import RecordPage from './components/RecordPage.svelte';
  import ReviewPage from './components/ReviewPage.svelte';
  import DatasetsPage from './components/DatasetsPage.svelte';
  import ExperimentsPage from './components/ExperimentsPage.svelte';
  import BenchPage from './components/BenchPage.svelte';
  import LocatePage from './components/LocatePage.svelte';
  import { app } from './lib/store.svelte';

  type Path = '/' | '/live' | '/device' | '/record' | '/review' | '/datasets' | '/experiments' | '/bench' | '/locate';
  const LATER: string[] = [];
  const GROUPS: { name: string; pages: { path: Path; label: string }[] }[] = [
    {
      name: 'Capture',
      pages: [
        { path: '/live', label: 'Live' },
        { path: '/device', label: 'Device' },
        { path: '/record', label: 'Record' },
      ],
    },
    {
      name: 'Data',
      pages: [
        { path: '/review', label: 'Review' },
        { path: '/datasets', label: 'Datasets' },
        { path: '/experiments', label: 'Experiments' },
      ],
    },
    {
      name: 'Test',
      pages: [
        { path: '/bench', label: 'Bench' },
        { path: '/locate', label: 'Locate' },
      ],
    },
  ];

  let path = $state(normalise(location.pathname));

  function normalise(p: string): Path {
    if (p.startsWith('/device')) return '/device';
    if (p.startsWith('/record')) return '/record';
    if (p.startsWith('/review')) return '/review';
    if (p.startsWith('/datasets')) return '/datasets';
    if (p.startsWith('/bench')) return '/bench';
    if (p.startsWith('/experiments')) return '/experiments';
    if (p.startsWith('/locate')) return '/locate';
    if (p.startsWith('/live')) return '/live';
    return '/';
  }

  const LEAVE_REVIEW = 'The Review page has unsaved label changes. Leave the page and lose them?';

  /** Leaving the Review page with unsaved edits needs a yes (the page's own state is lost when it unmounts). */
  function mayLeave(to: Path): boolean {
    if (path !== '/review' || to === '/review' || !app.reviewDirty) return true;
    if (!confirm(LEAVE_REVIEW)) return false;
    app.reviewDirty = false;
    return true;
  }

  function goTo(to: string): void {
    const p = normalise(to);
    if (!mayLeave(p)) return;
    if (path !== p) history.pushState({}, '', p);
    path = p;
    here = location.pathname + location.search;
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

{#if path === '/'}
  <HomePage onGo={goTo} groups={GROUPS} />
{:else}
<div class="shell">
  <nav class="rail" aria-label="Pages">
    <div class="brand">
      <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden="true">
        <rect width="32" height="32" rx="6" fill="var(--panel2)" />
        <path d="M3 17h5l3-9 5 17 4-14 3 6h6" fill="none" stroke="var(--accent)" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round" />
      </svg>
      <span>Rezonating Lab</span>
    </div>
    <a href="/" onclick={(e) => go(e, '/')}>Home</a>
    {#each GROUPS as grp (grp.name)}
      <span class="group">{grp.name}</span>
      {#each grp.pages as p (p.path)}
        <a href={p.path} class:active={path === p.path} onclick={(e) => go(e, p.path)} aria-current={path === p.path ? 'page' : undefined}>
          {p.label}{#if p.path === '/record' && app.recActive}<span class="dot rec on" style="margin-left:8px" aria-label="recording"></span>{/if}
        </a>
      {/each}
    {/each}
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
      {:else if path === '/locate'}
        <LocatePage />
      {:else}
        <RecordPage />
      {/if}
    </main>
  </div>
</div>
{/if}
<Toasts />
