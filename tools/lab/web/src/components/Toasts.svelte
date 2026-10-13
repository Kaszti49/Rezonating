<script lang="ts">
  import { app } from '../lib/store.svelte';
</script>

<div class="toasts" aria-live="polite">
  {#each app.toasts as t (t.key)}
    <div class="toast {t.kind}" role={t.kind === 'error' ? 'alert' : 'status'}>
      <span>{t.text}</span>
      <button onclick={() => app.dismiss(t.key)} aria-label="Dismiss">&times;</button>
    </div>
  {/each}
</div>
