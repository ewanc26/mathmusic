<script lang="ts">
  import type { Snippet } from "svelte";

  interface Props {
    label: string;
    hint?: string;
    children: Snippet;
    class?: string;
  }

  let { label, hint = "", children, class: className = "" }: Props = $props();
</script>

<label class="mb-2.5 flex flex-col gap-1 {className}">
  <span class="field-label">{label}</span>
  {@render children()}
  {#if hint}<span class="hint">{hint}</span>{/if}
</label>
