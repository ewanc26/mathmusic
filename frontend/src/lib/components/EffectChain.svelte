<!-- An effects chain (a track's or the master's): cards run top to bottom. -->
<script lang="ts">
  import { ArrowDown, ArrowUp, X } from "@lucide/svelte";
  import { daw } from "$lib/daw.svelte";
  import type { Effect, RenderError } from "$lib/types";
  import Check from "./fields/Check.svelte";
  import Errors from "./fields/Errors.svelte";
  import ParamControl from "./ParamControl.svelte";

  let { chain, errors }: { chain: Effect[]; errors: RenderError[] } = $props();

  function add(type: string) {
    const spec = daw.catalogue.effects[type];
    if (!spec) return;
    const params = Object.fromEntries(Object.entries(spec).map(([name, p]) => [name, p.default]));
    daw.edit(() => chain.push({ type, bypass: false, params }));
  }

  function move(index: number, delta: number) {
    const target = index + delta;
    if (target < 0 || target >= chain.length) return;
    daw.edit(() => ([chain[index], chain[target]] = [chain[target], chain[index]]));
  }
</script>

<div class="flex flex-col gap-2.5">
  {#each chain as effect, index (index + effect.type)}
    <div class="rounded-2xl border border-line bg-panel-2 px-3 py-2.5">
      <div class="mb-1.5 flex items-center gap-2">
        <strong class="text-xs tracking-wider uppercase">{effect.type}</strong>
        <Check label="bypass" checked={effect.bypass} onchange={(v) => (effect.bypass = v)} />
        <span class="flex-1"></span>
        <button
          class="rounded p-0.5 text-muted hover:text-ink"
          type="button"
          title="Move up"
          aria-label="Move up"
          onclick={() => move(index, -1)}><ArrowUp size={14} /></button
        >
        <button
          class="rounded p-0.5 text-muted hover:text-ink"
          type="button"
          title="Move down"
          aria-label="Move down"
          onclick={() => move(index, 1)}><ArrowDown size={14} /></button
        >
        <button
          class="rounded p-0.5 text-muted hover:text-bad"
          type="button"
          title="Remove effect"
          aria-label="Remove effect"
          onclick={() => daw.edit(() => chain.splice(index, 1))}><X size={14} /></button
        >
      </div>
      <div class="grid grid-cols-[repeat(auto-fill,minmax(230px,1fr))] gap-x-3.5">
        {#each Object.entries(daw.catalogue.effects[effect.type] ?? {}) as [name, spec] (name)}
          <ParamControl {effect} {name} {spec} />
        {/each}
      </div>
      <Errors errors={errors.filter((e) => e.field === `effects[${index}]`)} />
    </div>
  {:else}
    <p class="hint">No effects. Add one below; they run top to bottom.</p>
  {/each}
  <select
    class="input self-start"
    aria-label="Add effect"
    value=""
    onchange={(e) => {
      add(e.currentTarget.value);
      e.currentTarget.value = "";
    }}
  >
    <option value="">+ Add effect…</option>
    {#each Object.keys(daw.catalogue.effects) as type (type)}<option value={type}>{type}</option>{/each}
  </select>
</div>
