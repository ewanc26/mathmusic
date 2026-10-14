<script lang="ts">
  import { toast } from "$lib/toast.svelte";
</script>

<div
  class="pointer-events-none fixed bottom-4.5 left-1/2 z-10 -translate-x-1/2 rounded-full border bg-panel-3 px-4 py-2 transition-all duration-200
    {toast.visible ? 'translate-y-0 opacity-100' : 'translate-y-5 opacity-0'}
    {toast.kind === 'err' ? 'border-bad text-bad' : toast.kind === 'ok' ? 'border-good/50' : 'border-line'}"
  role="status"
  aria-live="polite"
>
  {toast.text}
</div>
