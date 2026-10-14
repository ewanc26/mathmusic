<!-- Project, history, transport, tempo/key/time signature, export and status. -->
<script lang="ts">
  import { CircleHelp, Metronome, Pause, Play, Redo2, Repeat, SkipBack, Undo2 } from "@lucide/svelte";
  import { exportMidi, newProject, save, toggleLoop } from "$lib/actions.svelte";
  import { daw } from "$lib/daw.svelte";
  import { transport } from "$lib/transport.svelte";
  import { fmtPosition, fmtTime, parseNote, safeFilename } from "$lib/util";

  let { onopen, onhelp }: { onopen: () => void; onhelp: () => void } = $props();

  let bpmText = $state("");
  let rootText = $state("");
  let editingBpm = $state(false);
  let editingRoot = $state(false);

  $effect(() => {
    const bpm = String(daw.project.bpm);
    if (!editingBpm) bpmText = bpm;
  });
  $effect(() => {
    const root = daw.project.root;
    if (!editingRoot) rootText = root;
  });

  const bpmValid = $derived(Number.isFinite(Number(bpmText)) && Number(bpmText) >= 20 && Number(bpmText) <= 300);
  const rootValid = $derived.by(() => {
    const midi = parseNote(rootText);
    return midi !== null && midi >= 12 && midi <= 108;
  });

  const audioUrl = $derived(daw.render?.audio?.url ?? null);
  const fileName = $derived(safeFilename(daw.project.name));
  const pills = $derived([
    ["MP3 export", daw.status.ffmpeg],
    ["plyr.fm SDK", daw.status.plyrfm],
    ["PLYR_TOKEN", daw.status.plyr_token],
  ] as const);
</script>

<header class="flex min-h-[54px] flex-wrap items-center gap-3.5 border-b border-line px-3.5 py-2">
  <div
    class="bg-gradient-to-r from-neon-cyan via-neon-purple to-accent bg-clip-text font-display text-lg font-extrabold tracking-tight text-transparent"
  >
    mathmusic
  </div>

  <div class="flex items-center gap-1">
    <input
      class="input w-44 font-semibold"
      type="text"
      maxlength="64"
      spellcheck="false"
      aria-label="Project name"
      value={daw.project.name}
      oninput={(e) => daw.live((p) => (p.name = e.currentTarget.value))}
      onchange={daw.settle}
    />
    {#if daw.dirty}<span class="text-xs text-accent" title="Unsaved changes">●</span>{/if}
  </div>

  <div class="flex items-center gap-1.5">
    <button class="btn" type="button" onclick={newProject}>New</button>
    <button class="btn" type="button" onclick={onopen}>Open</button>
    <button class="btn" type="button" title="Save (⌘S)" onclick={save}>Save</button>
  </div>

  <div class="flex items-center gap-1.5">
    <button
      class="icon-btn"
      type="button"
      title="Undo (⌘Z)"
      aria-label="Undo"
      disabled={!daw.canUndo}
      onclick={daw.undo}
    >
      <Undo2 size={15} />
    </button>
    <button
      class="icon-btn"
      type="button"
      title="Redo (⇧⌘Z)"
      aria-label="Redo"
      disabled={!daw.canRedo}
      onclick={daw.redo}
    >
      <Redo2 size={15} />
    </button>
  </div>

  <div class="flex items-center gap-2">
    <button
      class="icon-btn"
      type="button"
      title="Back to start (Home)"
      aria-label="Back to start"
      onclick={transport.toStart}
    >
      <SkipBack size={15} />
    </button>
    <button
      class="inline-flex size-10 items-center justify-center rounded-full bg-accent text-white shadow-[0_0_22px_color-mix(in_srgb,var(--color-accent)_45%,transparent)]"
      type="button"
      title="Play / pause (Space)"
      aria-label={transport.playing ? "Pause" : "Play"}
      disabled={!transport.hasAudio}
      onclick={(e) => {
        e.currentTarget.blur();
        transport.toggle();
      }}
    >
      {#if transport.playing}<Pause size={17} fill="currentColor" />{:else}<Play size={17} fill="currentColor" />{/if}
    </button>
    <button
      class="icon-btn"
      class:on={daw.project.loop_enabled}
      type="button"
      title="Loop (L). Drag on the ruler to set the region."
      aria-label="Loop"
      aria-pressed={daw.project.loop_enabled}
      onclick={toggleLoop}
    >
      <Repeat size={15} />
    </button>
    <button
      class="icon-btn"
      class:on={transport.metronome.enabled}
      type="button"
      title="Metronome (K). Clicks are not part of the render or exports."
      aria-label="Metronome"
      aria-pressed={transport.metronome.enabled}
      onclick={() => transport.metronome.toggle()}
    >
      <Metronome size={15} />
    </button>
    <div class="flex min-w-[78px] flex-col leading-tight">
      <span class="font-mono text-[15px]" title="Bar.beat.hundredths">
        {fmtPosition(transport.beat, daw.project.beats_per_bar)}
      </span>
      <span class="readout">{fmtTime(transport.seconds)}</span>
    </div>
  </div>

  <div class="flex flex-wrap items-center gap-2 text-xs text-muted">
    <label class="inline-flex items-center gap-1.5">
      BPM
      <input
        class="input w-16"
        class:invalid={!bpmValid}
        type="number"
        min="20"
        max="300"
        bind:value={bpmText}
        onfocus={() => (editingBpm = true)}
        onblur={() => (editingBpm = false)}
        oninput={() => bpmValid && daw.live((p) => (p.bpm = Number(bpmText)))}
        onchange={() => {
          daw.settle();
          bpmText = String(daw.project.bpm);
        }}
      />
    </label>
    <label class="inline-flex items-center gap-1.5" title="Time signature: beats per bar (a beat is a quarter note)">
      Time
      <select
        class="input"
        value={String(daw.project.beats_per_bar)}
        onchange={(e) => daw.edit((p) => (p.beats_per_bar = Number(e.currentTarget.value)))}
      >
        {#each Array.from({ length: 16 }, (_, i) => i + 1) as n (n)}
          <option value={String(n)}>{n}/4</option>
        {/each}
      </select>
    </label>
    <label class="inline-flex items-center gap-1.5">
      Root
      <input
        class="input w-14"
        class:invalid={!rootValid}
        type="text"
        maxlength="4"
        spellcheck="false"
        bind:value={rootText}
        onfocus={() => (editingRoot = true)}
        onblur={() => (editingRoot = false)}
        oninput={() => rootValid && daw.live((p) => (p.root = rootText.trim()))}
        onchange={() => {
          daw.settle();
          rootText = daw.project.root;
        }}
      />
    </label>
    <label class="inline-flex items-center gap-1.5">
      Scale
      <select
        class="input"
        value={daw.project.scale}
        onchange={(e) => daw.edit((p) => (p.scale = e.currentTarget.value))}
      >
        {#each Object.keys(daw.catalogue.scales) as scale (scale)}
          <option value={scale}>{scale.replace("_", " ")}</option>
        {/each}
      </select>
    </label>
  </div>

  <div class="flex items-center gap-1.5">
    {#if audioUrl}
      <a class="btn" href={audioUrl} download="{fileName}.wav">WAV</a>
      {#if daw.status.ffmpeg}
        <a class="btn" href={audioUrl.replace(/\.wav$/, ".mp3")} download="{fileName}.mp3">MP3</a>
      {:else}
        <button class="btn" type="button" disabled title="MP3 export needs ffmpeg on your PATH">MP3</button>
      {/if}
    {/if}
    <button class="btn" type="button" title="Export the notes as a MIDI file for other DAWs" onclick={exportMidi}
      >MIDI</button
    >
    <button
      class="icon-btn"
      type="button"
      title="Keyboard shortcuts (?)"
      aria-label="Keyboard shortcuts"
      onclick={onhelp}
    >
      <CircleHelp size={15} />
    </button>
  </div>

  <div class="ml-auto flex flex-wrap gap-1.5">
    {#each pills as [label, ok] (label)}
      <span
        class="rounded-full border px-2 py-0.5 text-[11px] {ok ? 'border-good/40 text-good' : 'border-bad/40 text-bad'}"
        >{ok ? "✓" : "✕"} {label}</span
      >
    {/each}
  </div>
</header>
