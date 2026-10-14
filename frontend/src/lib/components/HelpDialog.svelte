<!-- Keyboard shortcuts and what x means in each kind of formula. -->
<script lang="ts">
  import { X } from "@lucide/svelte";

  let dialog = $state<HTMLDialogElement>();

  export function show() {
    dialog?.showModal();
  }

  const shortcuts: [string, string][] = [
    ["Space", "Play / pause"],
    ["Home or Enter", "Back to start (or loop start)"],
    ["L", "Loop on / off. Drag on the ruler to set the loop."],
    ["K", "Metronome on / off (not part of the render or exports)"],
    ["R", "Record from the microphone while the project plays; the take lands as an audio clip"],
    ["⌘Z, ⇧⌘Z", "Undo, redo"],
    ["⌘S", "Save"],
    ["⌘C, ⌘V, ⌘D", "Copy, paste, duplicate the selected clip"],
    ["⌘E", "Split the selected clip at the playhead"],
    ["⌫", "Delete the selected clip"],
    ["T", "Add a track"],
    ["M, S", "Mute, solo the selected track"],
    ["+, −, F", "Zoom in, out, fit"],
    ["1 – 7", "Clip, Track, Effects, Automation, Mixer, Master, Publish"],
    ["Double-click lane", "New clip (below the last track: new track)"],
    ["Drag clip", "Move, also to another track. Drag its right edge to resize."],
    ["Drop audio file", "Import it as an audio clip on that lane"],
    ["⌘/Ctrl + scroll", "Zoom the timeline. Shift + scroll pans."],
  ];
</script>

<dialog
  bind:this={dialog}
  class="m-auto w-[min(600px,calc(100vw-32px))] rounded-2xl border border-line bg-panel-2 px-5 py-4 text-ink"
>
  <div class="flex items-center justify-between">
    <h2 class="text-base font-semibold">Keyboard and mouse</h2>
    <button class="icon-btn" type="button" aria-label="Close" onclick={() => dialog?.close()}><X size={15} /></button>
  </div>
  <dl class="my-3 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5">
    {#each shortcuts as [keys, action] (keys)}
      <dt class="font-mono text-neon-cyan">{keys}</dt>
      <dd>{action}</dd>
    {/each}
  </dl>
  <p class="hint">
    Every formula uses x. In a clip x runs across the curve; in automation x is the beat; in a waveform x is the phase
    (one cycle from 0 to 1); in an envelope x runs over the note; in a shaper x is the sample value.
  </p>
</dialog>
