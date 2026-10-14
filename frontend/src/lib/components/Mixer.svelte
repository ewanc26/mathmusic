<!-- Channel strips: meters that follow the playhead, faders, pan, mute and solo. -->
<script lang="ts">
  import { daw } from "$lib/daw.svelte";
  import { drawMeter, levelAt } from "$lib/draw";
  import { transport } from "$lib/transport.svelte";
  import { trackColor } from "$lib/util";
  import Canvas from "./Canvas.svelte";

  const beat = $derived(transport.playing ? transport.beat : null);
  const perBeat = $derived(daw.render?.peaks_per_beat ?? 8);

  function db(value: number) {
    return value <= -60 ? "-∞" : `${value > 0 ? "+" : ""}${value.toFixed(1)}`;
  }
</script>

<p class="hint mb-2.5">Meters show the rendered level at the playhead. Double-click a fader for 0 dB.</p>
<div class="flex gap-2.5 overflow-x-auto pb-1.5">
  {#each daw.project.tracks as track, index (track.id)}
    <div
      class="flex w-[92px] flex-none flex-col items-center gap-2 rounded-xl border border-t-[3px] border-line bg-panel-2 px-1.5 py-2"
      style="border-top-color: {trackColor(index)}; {track.id === daw.selection.track
        ? `border-left-color: ${trackColor(index)}; border-right-color: ${trackColor(index)}; border-bottom-color: ${trackColor(index)}`
        : ''}"
    >
      <button
        class="w-full truncate text-center text-xs font-semibold"
        type="button"
        onclick={() => daw.select(track.id, null)}>{track.name}</button
      >
      <div class="flex h-[150px] gap-1.5">
        <Canvas
          class="h-full w-2.5 rounded-sm"
          aria-hidden="true"
          draw={(c) => drawMeter(c, levelAt(daw.trackRender(track.id)?.peaks, beat, perBeat))}
        />
        <div class="flex flex-col items-center gap-1">
          <input
            class="h-32 w-[22px] [direction:rtl] [writing-mode:vertical-lr]"
            type="range"
            min="-60"
            max="12"
            step="0.5"
            aria-label="{track.name} volume"
            value={track.volume_db}
            oninput={(e) => daw.live(() => (track.volume_db = Number(e.currentTarget.value)))}
            onchange={daw.settle}
            ondblclick={() => daw.edit(() => (track.volume_db = 0))}
          />
          <output class="readout text-[10px]">{db(track.volume_db)}</output>
        </div>
      </div>
      <input
        class="w-full"
        type="range"
        min="-1"
        max="1"
        step="0.05"
        aria-label="{track.name} pan"
        title="Pan (double-click to centre)"
        value={track.pan}
        oninput={(e) => daw.live(() => (track.pan = Number(e.currentTarget.value)))}
        onchange={daw.settle}
        ondblclick={() => daw.edit(() => (track.pan = 0))}
      />
      <div class="flex gap-1">
        <button
          class="ms mute"
          class:on={track.mute}
          type="button"
          onclick={() => daw.edit(() => (track.mute = !track.mute))}>M</button
        >
        <button
          class="ms solo"
          class:on={track.solo}
          type="button"
          onclick={() => daw.edit(() => (track.solo = !track.solo))}>S</button
        >
      </div>
    </div>
  {/each}
  <div
    class="flex w-[92px] flex-none flex-col items-center gap-2 rounded-xl border border-t-[3px] border-line border-t-accent bg-panel-3 px-1.5 py-2"
  >
    <div class="text-xs font-semibold">Master</div>
    <div class="flex h-[150px] gap-1.5">
      <Canvas
        class="h-full w-2.5 rounded-sm"
        aria-hidden="true"
        draw={(c) => drawMeter(c, levelAt(daw.render?.master_peaks, beat, perBeat))}
      />
      <div class="flex flex-col items-center gap-1">
        <input
          class="h-32 w-[22px] [direction:rtl] [writing-mode:vertical-lr]"
          type="range"
          min="-60"
          max="12"
          step="0.5"
          aria-label="Master volume"
          value={daw.project.master.volume_db}
          oninput={(e) => daw.live((p) => (p.master.volume_db = Number(e.currentTarget.value)))}
          onchange={daw.settle}
          ondblclick={() => daw.edit((p) => (p.master.volume_db = 0))}
        />
        <output class="readout text-[10px]">{db(daw.project.master.volume_db)}</output>
      </div>
    </div>
    <p class="hint m-0 text-[10px]">{daw.project.master.normalize ? "normalised" : ""}</p>
  </div>
</div>
