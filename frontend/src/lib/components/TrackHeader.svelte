<!-- One track's header beside its lane: name, mute/solo, delete, volume and pan. -->
<script lang="ts">
  import { X } from "@lucide/svelte";
  import { daw } from "$lib/daw.svelte";
  import { TRACK_HEIGHT } from "$lib/view.svelte";
  import type { Track } from "$lib/types";
  import { fmtDb, fmtPan, trackColor } from "$lib/util";

  let { track, index }: { track: Track; index: number } = $props();

  const selected = $derived(daw.selection.track === track.id);
  const info = $derived(daw.trackRender(track.id));

  function focusTrack(event: Event) {
    if (event.type === "mousedown" && (event.target as HTMLElement).closest("button")) return;
    // keep the selected clip if it belongs to this track
    const keep = track.clips.some((c) => c.id === daw.selection.clip) ? daw.selection.clip : null;
    if (daw.selection.track !== track.id || daw.selection.clip !== keep) daw.select(track.id, keep);
  }

  function remove() {
    daw.edit((p) => {
      p.tracks = p.tracks.filter((t) => t.id !== track.id);
    });
    if (daw.selection.track === track.id) daw.select(daw.project.tracks[0]?.id ?? null, null);
  }
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions (pointer and focus inside the header select its track; every control is itself focusable) -->
<div
  class="relative flex flex-col justify-center gap-0.5 border-b border-line py-1.5 pr-2 pl-3"
  class:bg-panel-2={selected}
  class:opacity-55={info?.audible === false}
  style="height: {TRACK_HEIGHT}px; --track-color: {trackColor(index)}"
  role="group"
  aria-label="Track {track.name}"
  onmousedown={focusTrack}
  onfocusin={focusTrack}
>
  <span class="absolute inset-y-0 left-0 w-1 bg-[var(--track-color)]"></span>
  <div class="flex items-center gap-1">
    <span class="size-2.5 flex-none rounded-full bg-[var(--track-color)]"></span>
    <input
      class="min-w-0 flex-1 rounded-md border border-transparent bg-transparent px-1 py-px font-semibold hover:border-line focus:border-line focus:bg-panel-3"
      type="text"
      maxlength="80"
      spellcheck="false"
      aria-label="Track name"
      value={track.name}
      oninput={(e) => daw.live(() => (track.name = e.currentTarget.value))}
      onchange={daw.settle}
    />
    <button
      class="ms mute"
      class:on={track.mute}
      type="button"
      title="Mute (M)"
      aria-pressed={track.mute}
      onclick={() => daw.edit(() => (track.mute = !track.mute))}>M</button
    >
    <button
      class="ms solo"
      class:on={track.solo}
      type="button"
      title="Solo (S)"
      aria-pressed={track.solo}
      onclick={() => daw.edit(() => (track.solo = !track.solo))}>S</button
    >
    <button
      class="rounded-md p-0.5 text-muted hover:text-bad"
      type="button"
      title="Delete track (undo with ⌘Z)"
      aria-label="Delete track"
      onclick={remove}><X size={14} /></button
    >
  </div>
  <div class="flex items-center gap-1 text-[11px] text-muted">
    <span class="w-6">vol</span>
    <input
      class="h-3.5 min-w-0 flex-1"
      type="range"
      min="-60"
      max="12"
      step="0.5"
      aria-label="Volume"
      title="Volume (double-click for 0 dB)"
      value={track.volume_db}
      oninput={(e) => daw.live(() => (track.volume_db = Number(e.currentTarget.value)))}
      onchange={daw.settle}
      ondblclick={() => daw.edit(() => (track.volume_db = 0))}
    />
    <output class="readout w-[58px] text-right text-[11px] whitespace-nowrap">{fmtDb(track.volume_db)}</output>
  </div>
  <div class="flex items-center gap-1 text-[11px] text-muted">
    <span class="w-6">pan</span>
    <input
      class="h-3.5 min-w-0 flex-1"
      type="range"
      min="-1"
      max="1"
      step="0.05"
      aria-label="Pan"
      title="Pan (double-click to centre)"
      value={track.pan}
      oninput={(e) => daw.live(() => (track.pan = Number(e.currentTarget.value)))}
      onchange={daw.settle}
      ondblclick={() => daw.edit(() => (track.pan = 0))}
    />
    <output class="readout w-7 text-right text-[11px]">{fmtPan(track.pan)}</output>
    <span class="max-w-[64px] truncate font-mono" title={info?.sound ?? ""}>{info?.sound ?? track.sound ?? ""}</span>
  </div>
</div>
