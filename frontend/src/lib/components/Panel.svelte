<!-- The editor panel: Clip, Track, Effects, Automation, Mixer, Master and Publish tabs. -->
<script lang="ts" module>
  export const TABS = [
    ["clip", "Clip"],
    ["track", "Track"],
    ["effects", "Effects"],
    ["automation", "Automation"],
    ["mixer", "Mixer"],
    ["master", "Master"],
    ["publish", "Publish"],
  ] as const;

  export type Tab = (typeof TABS)[number][0];
</script>

<script lang="ts">
  import { daw } from "$lib/daw.svelte";
  import AutomationEditor from "./AutomationEditor.svelte";
  import ClipEditor from "./ClipEditor.svelte";
  import EffectChain from "./EffectChain.svelte";
  import MasterEditor from "./MasterEditor.svelte";
  import Mixer from "./Mixer.svelte";
  import PublishPanel from "./PublishPanel.svelte";
  import TrackEditor from "./TrackEditor.svelte";

  let { tab = $bindable("clip"), expressionInput = $bindable() }: { tab?: Tab; expressionInput?: HTMLInputElement } =
    $props();

  const track = $derived(daw.selectedTrack);

  function onTabKey(event: KeyboardEvent, index: number) {
    const step = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    tab = TABS[(index + step + TABS.length) % TABS.length][0];
    document.getElementById(`tab-${tab}`)?.focus();
  }
</script>

<section class="grid min-h-0 grid-rows-[auto_1fr] bg-panel" aria-label="Editor">
  <div class="flex gap-0.5 overflow-x-auto border-b border-line px-2.5 pt-1.5 whitespace-nowrap" role="tablist">
    {#each TABS as [key, label], i (key)}
      <button
        class="border-b-2 px-3 py-1.5 font-semibold {tab === key
          ? 'border-accent text-ink'
          : 'border-transparent text-muted'}"
        type="button"
        role="tab"
        id="tab-{key}"
        aria-controls="panel-{key}"
        aria-selected={tab === key}
        tabindex={tab === key ? 0 : -1}
        onclick={() => (tab = key)}
        onkeydown={(event) => onTabKey(event, i)}>{label}</button
      >
    {/each}
  </div>
  <div
    class="min-h-0 overflow-auto px-4 pt-3 pb-5"
    role="tabpanel"
    id="panel-{tab}"
    aria-labelledby="tab-{tab}"
    tabindex="0"
  >
    {#if tab === "clip"}
      <ClipEditor bind:expressionInput />
    {:else if tab === "track"}
      <TrackEditor />
    {:else if tab === "effects"}
      {#if track}
        <h3 class="mb-2.5 text-xs tracking-widest text-muted uppercase">Effects on {track.name}</h3>
        <EffectChain chain={track.effects} errors={daw.errorsFor(track.id, null)} />
      {:else}
        <p class="py-6 text-muted">Select a track to edit its effects.</p>
      {/if}
    {:else if tab === "automation"}
      <AutomationEditor />
    {:else if tab === "mixer"}
      <Mixer />
    {:else if tab === "master"}
      <MasterEditor />
    {:else}
      <PublishPanel />
    {/if}
  </div>
</section>
