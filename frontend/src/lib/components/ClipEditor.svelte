<!-- The selected clip: a curve (formula, sampling, pitch mapping, graph) or an audio sample. -->
<script lang="ts">
  import { deleteClip, duplicateClip, splitClip } from "$lib/actions.svelte";
  import { daw } from "$lib/daw.svelte";
  import { drawClipGraph, drawPeaks, type Geometry } from "$lib/draw";
  import { transport } from "$lib/transport.svelte";
  import type { Sample } from "$lib/types";
  import { noteName, parseNote, pitchTable, trackColor } from "$lib/util";
  import Canvas from "./Canvas.svelte";
  import Check from "./fields/Check.svelte";
  import Errors from "./fields/Errors.svelte";
  import NumberField from "./fields/NumberField.svelte";
  import RangeField from "./fields/RangeField.svelte";
  import SelectField from "./fields/SelectField.svelte";
  import TextField from "./fields/TextField.svelte";

  let { expressionInput = $bindable() }: { expressionInput?: HTMLInputElement } = $props();

  const found = $derived(daw.clip(daw.selection.clip));
  const clip = $derived(found?.clip ?? null);
  const color = $derived(found ? trackColor(daw.project.tracks.indexOf(found.track)) : "#25f4ee");
  const rendered = $derived(clip ? daw.clipRender(clip.id) : null);
  const errors = $derived(found && clip ? daw.errorsFor(found.track.id, clip.id) : []);
  const playBeat = $derived(transport.hasAudio && (transport.playing || transport.beat > 0) ? transport.beat : null);

  let hover = $state<Sample | null>(null);
  let geometry: Geometry | null = null;

  function drawCurve(canvas: HTMLCanvasElement) {
    if (!clip || rendered?.kind !== "curve") return;
    const degrees = daw.catalogue.scales[daw.project.scale] ?? [0];
    const root = (parseNote(daw.project.root) ?? 60) + 12 * clip.octave;
    geometry = drawClipGraph(canvas, {
      samples: rendered.samples,
      bounds: rendered.bounds ?? [0, 1],
      pitches: pitchTable(degrees, root, clip.octaves),
      invert: clip.invert,
      stroke: color,
      playBeat,
      hover,
    });
  }

  function drawAudio(canvas: HTMLCanvasElement) {
    if (!clip || rendered?.kind !== "audio") return;
    const fraction = playBeat === null ? null : (playBeat - clip.start) / clip.length;
    drawPeaks(canvas, rendered.peaks, color, fraction);
  }

  function hoverCurve(event: MouseEvent) {
    if (!geometry || rendered?.kind !== "curve") return;
    const x = event.clientX - (event.currentTarget as HTMLElement).getBoundingClientRect().left;
    let best: Sample | null = null;
    let distance = Infinity;
    for (const s of rendered.samples) {
      const d = Math.abs(geometry.X(s.x) - x);
      if (d < distance) [best, distance] = [s, d];
    }
    hover = best && best.y !== null ? best : null;
  }

  function setFixedRange(fixed: boolean) {
    if (!clip) return;
    if (!fixed) {
      clip.y_min = null;
      clip.y_max = null;
      return;
    }
    const bounds = rendered?.kind === "curve" && rendered.bounds ? rendered.bounds : [-1, 1];
    clip.y_min = Number(bounds[0].toFixed(4));
    clip.y_max = Number((bounds[1] > bounds[0] ? bounds[1] : bounds[0] + 1).toFixed(4));
  }

  const octaves: [string, string][] = [-3, -2, -1, 0, 1, 2, 3].map((o) => [String(o), o > 0 ? `+${o}` : String(o)]);
</script>

{#if !clip}
  <p class="max-w-xl py-6 text-muted">
    Select a clip, or double-click a lane to create one. Each curve clip plays y = f(x): x runs across the clip and y
    sets the pitch. Import audio with the Audio button or by dropping a file on a lane.
  </p>
{:else if clip.kind === "audio"}
  <div class="grid grid-cols-[minmax(300px,400px)_1fr] gap-4.5 max-[900px]:grid-cols-1">
    <div>
      <TextField label="Clip name" value={clip.name} mono={false} maxlength={80} onlive={(v) => (clip.name = v)} />
      <Errors {errors} />
      <div class="grid grid-cols-2 gap-x-3">
        <NumberField label="Start (beat)" value={clip.start} min={0} max={2048} onlive={(v) => (clip.start = v)} />
        <NumberField
          label="Length (beats)"
          value={clip.length}
          min={0.25}
          max={2048}
          onlive={(v) => (clip.length = v)}
        />
        <NumberField
          label="Offset into the sample (beats)"
          value={clip.offset}
          min={0}
          max={2048}
          onlive={(v) => (clip.offset = v)}
        />
        <RangeField label="Gain" value={clip.gain} min={0} max={2} step={0.01} onlive={(v) => (clip.gain = v)} />
        <NumberField
          label="Fade in (beats)"
          value={clip.fade_in}
          min={0}
          max={clip.length}
          step={0.25}
          onlive={(v) => (clip.fade_in = v)}
        />
        <NumberField
          label="Fade out (beats)"
          value={clip.fade_out}
          min={0}
          max={clip.length}
          step={0.25}
          onlive={(v) => (clip.fade_out = v)}
        />
      </div>
      <TextField
        label="Fade shape (x runs 0 to 1 across the fade)"
        value={clip.fade_curve}
        placeholder="x  (linear); x*x  (slow start); sqrt(x)  (fast start)"
        onlive={(v) => (clip.fade_curve = v.trim() ? v : "x")}
      />
      <Errors errors={errors.filter((e) => e.field === "fade_curve")} />
      {#if rendered?.kind === "audio" && rendered.seconds}
        <p class="hint">
          Sample length {rendered.seconds.toFixed(2)} s = {(rendered.seconds / transport.secondsPerBeat).toFixed(2)} beats
          at
          {daw.project.bpm} BPM.
        </p>
      {/if}
      <div class="mt-2 flex flex-wrap gap-2">
        <button class="btn" type="button" onclick={duplicateClip}>Duplicate (⌘D)</button>
        <button class="btn" type="button" onclick={splitClip}>Split at playhead (⌘E)</button>
        <button class="btn danger" type="button" onclick={deleteClip}>Delete (⌫)</button>
      </div>
    </div>
    <div class="min-w-0">
      <div class="mb-1 text-[11px] tracking-widest text-muted uppercase">Waveform</div>
      <Canvas draw={drawAudio} class="panel-canvas h-[220px]" aria-label="Waveform of the audio clip" />
    </div>
  </div>
{:else}
  <div class="grid grid-cols-[minmax(300px,400px)_1fr] gap-4.5 max-[900px]:grid-cols-1">
    <div>
      <TextField
        label="y = f(x)"
        id="clip-expression"
        big
        bind:element={expressionInput}
        value={clip.expression}
        placeholder="y = f(x), e.g. sin(x)"
        onlive={(v) => (clip.expression = v)}
      />
      <Errors {errors} />
      <div class="grid grid-cols-2 gap-x-3">
        <NumberField label="x from" value={clip.x_start} min={-1e6} max={1e6} onlive={(v) => (clip.x_start = v)} />
        <NumberField label="x to" value={clip.x_end} min={-1e6} max={1e6} onlive={(v) => (clip.x_end = v)} />
        <NumberField
          label="Notes (samples of the curve)"
          value={clip.notes}
          min={1}
          max={1024}
          step={1}
          integer
          onlive={(v) => (clip.notes = v)}
        />
        <SelectField
          label="Rhythm"
          value={clip.rhythm}
          options={[
            ["uniform", "uniform"],
            ["slope", "follow slope"],
          ]}
          onchange={(v) => (clip.rhythm = v as "uniform" | "slope")}
        />
        <NumberField label="Start (beat)" value={clip.start} min={0} max={2048} onlive={(v) => (clip.start = v)} />
        <NumberField
          label="Length (beats)"
          value={clip.length}
          min={0.25}
          max={2048}
          onlive={(v) => (clip.length = v)}
        />
        <SelectField
          label="Octave"
          value={String(clip.octave)}
          options={octaves}
          onchange={(v) => (clip.octave = Number(v))}
        />
        <SelectField
          label="Range (octaves)"
          value={String(clip.octaves)}
          options={["1", "2", "3", "4"].map((o) => [o, o] as [string, string])}
          onchange={(v) => (clip.octaves = Number(v))}
        />
        <RangeField
          label="Gate"
          value={clip.gate}
          min={0.05}
          max={1}
          step={0.01}
          format={(v) => `${Math.round(v * 100)}%`}
          onlive={(v) => (clip.gate = v)}
        />
        <RangeField label="Gain" value={clip.gain} min={0} max={2} step={0.01} onlive={(v) => (clip.gain = v)} />
      </div>
      <Check label="Invert (high values sound low)" checked={clip.invert} onchange={(v) => (clip.invert = v)} />
      <div class="mt-1 grid grid-cols-2 gap-x-3 border-t border-line pt-2">
        <div class="col-span-2">
          <Check
            label="Fixed y range (otherwise the curve's own min and max)"
            checked={clip.y_min !== null}
            onchange={setFixedRange}
          />
        </div>
        <NumberField
          label="y at lowest note"
          value={clip.y_min}
          disabled={clip.y_min === null}
          min={-1e9}
          max={1e9}
          onlive={(v) => (clip.y_min = v)}
        />
        <NumberField
          label="y at highest note"
          value={clip.y_max}
          disabled={clip.y_min === null}
          min={-1e9}
          max={1e9}
          onlive={(v) => (clip.y_max = v)}
        />
      </div>
      <TextField
        label="Clip name"
        value={clip.name}
        mono={false}
        maxlength={80}
        placeholder="optional"
        onlive={(v) => (clip.name = v)}
      />
      <div class="flex flex-wrap gap-2">
        <button class="btn" type="button" onclick={duplicateClip}>Duplicate (⌘D)</button>
        <button class="btn" type="button" title="Split the clip where the playhead is" onclick={splitClip}>
          Split at playhead (⌘E)
        </button>
        <button class="btn danger" type="button" onclick={deleteClip}>Delete (⌫)</button>
      </div>
    </div>
    <div class="flex min-w-0 flex-col gap-1.5">
      <Canvas
        draw={drawCurve}
        class="h-[300px] w-full rounded-2xl border border-line bg-[radial-gradient(ellipse_at_50%_0%,color-mix(in_srgb,var(--color-neon-purple)_12%,transparent),transparent_60%),var(--color-stage)]"
        aria-label="Graph of the clip's curve and the notes it plays"
        onmousemove={hoverCurve}
        onmouseleave={() => (hover = null)}
      />
      <div class="readout min-h-[1.4em]">
        {#if hover}
          x = {hover.x.toFixed(3)} &nbsp; y = {hover.y?.toFixed(3) ?? "undefined"} &nbsp;
          {hover.pitch === null ? "rest" : `note ${noteName(hover.pitch)}`} &nbsp; beat {hover.start.toFixed(2)}
        {:else}
          Hover the curve to read values. Each horizontal line is a note of the scale; ticks show where each sample
          lands.
        {/if}
      </div>
    </div>
  </div>
{/if}
