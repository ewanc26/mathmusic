<!-- Text or a formula, edited live; the model is not written back while typing. -->
<script lang="ts">
  import { daw } from "$lib/daw.svelte";
  import Field from "./Field.svelte";

  interface Props {
    label?: string;
    value: string | null;
    onlive: (value: string) => void;
    placeholder?: string;
    mono?: boolean;
    big?: boolean;
    maxlength?: number;
    hint?: string;
    id?: string;
    element?: HTMLInputElement;
  }

  let {
    label = "",
    value,
    onlive,
    placeholder = "",
    mono = true,
    big = false,
    maxlength = 300,
    hint = "",
    id,
    element = $bindable(),
  }: Props = $props();

  let text = $state("");
  let focused = $state(false);

  $effect(() => {
    const shown = value ?? "";
    if (!focused) text = shown;
  });
</script>

{#snippet control()}
  <input
    bind:this={element}
    {id}
    class="input w-full"
    class:mono
    class:text-base={big}
    class:py-2={big}
    type="text"
    spellcheck="false"
    autocomplete="off"
    {placeholder}
    {maxlength}
    bind:value={text}
    oninput={() => daw.live(() => onlive(text))}
    onchange={daw.settle}
    onfocus={() => (focused = true)}
    onblur={() => (focused = false)}
  />
{/snippet}

{#if label}
  <Field {label} {hint}>{@render control()}</Field>
{:else}
  {@render control()}
{/if}
