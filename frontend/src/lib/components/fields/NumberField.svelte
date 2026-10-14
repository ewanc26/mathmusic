<!-- A number edited live (one undo step per change), validated against its range. -->
<script lang="ts">
  import { daw } from "$lib/daw.svelte";
  import { fmtNumber } from "$lib/util";
  import Field from "./Field.svelte";

  interface Props {
    label: string;
    value: number | null;
    onlive: (value: number) => void;
    min?: number;
    max?: number;
    step?: number | "any";
    integer?: boolean;
    disabled?: boolean;
    hint?: string;
  }

  let { label, value, onlive, min, max, step = "any", integer = false, disabled = false, hint = "" }: Props = $props();

  let text = $state("");
  let focused = $state(false);
  let invalid = $state(false);

  $effect(() => {
    const shown = fmtNumber(value);
    if (!focused) text = shown;
  });

  function input() {
    const number = Number(text);
    const ok =
      text.trim() !== "" &&
      Number.isFinite(number) &&
      (min === undefined || number >= min) &&
      (max === undefined || number <= max) &&
      (!integer || Number.isInteger(number));
    invalid = !ok;
    if (ok) daw.live(() => onlive(number));
  }

  function change() {
    invalid = false;
    daw.settle();
    text = fmtNumber(value);
  }
</script>

<Field {label} {hint}>
  <input
    class="input"
    class:invalid
    type="number"
    {min}
    {max}
    {step}
    {disabled}
    bind:value={text}
    oninput={input}
    onchange={change}
    onfocus={() => (focused = true)}
    onblur={() => (focused = false)}
  />
</Field>
