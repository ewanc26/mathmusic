<script lang="ts">
  import type { Snippet } from "svelte";
  import { daw } from "$lib/daw.svelte";
  import Field from "./Field.svelte";

  interface Props {
    label: string;
    value: string;
    onchange: (value: string) => void;
    options?: [string, string][];
    children?: Snippet;
  }

  let { label, value, onchange, options = [], children }: Props = $props();
</script>

<Field {label}>
  <select class="input w-full" {value} onchange={(e) => daw.edit(() => onchange(e.currentTarget.value))}>
    {#each options as [optionValue, optionLabel] (optionValue)}
      <option value={optionValue}>{optionLabel}</option>
    {/each}
    {@render children?.()}
  </select>
</Field>
