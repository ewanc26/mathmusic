<script lang="ts">
  import { daw } from "$lib/daw.svelte";

  interface Props {
    label: string;
    checked: boolean;
    onchange: (checked: boolean) => void;
    title?: string;
  }

  let { label, checked, onchange, title }: Props = $props();
</script>

<label class="mr-3 mb-2 inline-flex items-center gap-1.5 text-xs text-muted" {title}>
  <input type="checkbox" {checked} onchange={(e) => daw.edit(() => onchange(e.currentTarget.checked))} />
  {label}
</label>
