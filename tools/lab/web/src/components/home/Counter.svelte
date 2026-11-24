<script lang="ts">
  // A number that rolls up to its value.
  import { Tween } from 'svelte/motion';
  import { cubicOut } from 'svelte/easing';
  import { reducedMotion } from '../../lib/home';

  interface Props {
    value: number;
    digits?: number;
  }
  let { value, digits = 0 }: Props = $props();

  const t = new Tween(0, { duration: reducedMotion() ? 0 : 900, easing: cubicOut });
  $effect(() => {
    void t.set(value);
  });
  const text = $derived(t.current.toLocaleString('en', { minimumFractionDigits: digits, maximumFractionDigits: digits }));
</script>

<span class="roll">{text}</span>

<style>
  .roll {
    font-variant-numeric: tabular-nums;
  }
</style>
