<!--
  One effect parameter. A formula param (the shaper's transfer curve) is a formula of
  the sample value. An automatable number can switch (ƒ) to a formula of the beat,
  plotted over the song and clamped to the param's range.
-->
<script lang="ts">
  import { daw } from "$lib/daw.svelte";
  import { transport } from "$lib/transport.svelte";
  import type { Effect, ParamSpec } from "$lib/types";
  import RangeField from "./fields/RangeField.svelte";
  import TextField from "./fields/TextField.svelte";
  import FormulaPlot from "./FormulaPlot.svelte";

  let { effect, name, spec }: { effect: Effect; name: string; spec: ParamSpec } = $props();

  const value = $derived(effect.params[name]);
  const automated = $derived(spec.kind === "number" && typeof value === "string");
  const marker = $derived(transport.hasAudio && (transport.playing || transport.beat > 0) ? transport.beat : null);

  function format(v: number): string {
    if (name === "cutoff") return `${Math.round(v)} Hz`;
    if (name === "time") return `${v.toFixed(3)} beats`;
    return v.toFixed(2);
  }

  function toggleAutomation() {
    if (spec.kind !== "number") return;
    daw.edit(() => {
      effect.params[name] = typeof value === "string" ? spec.default : String(value);
    });
  }
</script>

{#if spec.kind === "formula"}
  <div class="col-span-full grid grid-cols-2 items-start gap-3 max-[900px]:grid-cols-1">
    <TextField label="{name} (x = sample value)" value={String(value)} onlive={(v) => (effect.params[name] = v)} />
    <FormulaPlot
      formula={String(value)}
      start={-1.5}
      end={1.5}
      stroke="#facc15"
      xLabel="in"
      class="h-[110px]"
      label="Transfer curve"
    />
  </div>
{:else if automated}
  <div class="col-span-full grid grid-cols-2 items-start gap-3 max-[900px]:grid-cols-1">
    <div>
      <div class="flex items-end gap-2">
        <div class="flex-1">
          <TextField
            label="{name} = f(x), x = beat ({spec.min} … {spec.max})"
            value={String(value)}
            onlive={(v) => (effect.params[name] = v)}
          />
        </div>
        <button
          class="icon-btn on mb-2.5"
          type="button"
          title="Back to a fixed value"
          aria-label="Fixed value"
          onclick={toggleAutomation}>ƒ</button
        >
      </div>
    </div>
    <FormulaPlot
      formula={String(value)}
      start={0}
      end={daw.songLength}
      yRange={name === "cutoff" ? null : [spec.min, spec.max]}
      stroke="#34d399"
      xLabel="beat"
      {marker}
      points={400}
      class="h-[110px]"
      label="{name} automation"
    />
  </div>
{:else}
  <div class="flex items-end gap-2">
    <div class="flex-1">
      <RangeField
        label={name}
        value={Number(value)}
        min={spec.min}
        max={spec.max}
        log={name === "cutoff"}
        {format}
        onlive={(v) => (effect.params[name] = v)}
      />
    </div>
    {#if spec.automatable}
      <button
        class="icon-btn mb-2.5"
        type="button"
        title="Automate: make this a formula of the beat"
        aria-label="Automate {name}"
        onclick={toggleAutomation}>ƒ</button
      >
    {/if}
  </div>
{/if}
