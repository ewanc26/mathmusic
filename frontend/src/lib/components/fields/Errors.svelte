<script lang="ts">
  import type { RenderError } from "$lib/types";

  let { errors }: { errors: RenderError[] } = $props();
</script>

{#if errors.length}
  <div class="-mt-1 mb-2 font-mono text-xs break-words text-bad" role="alert">
    {errors.map((e) => e.error).join(" · ")}
  </div>
{/if}
