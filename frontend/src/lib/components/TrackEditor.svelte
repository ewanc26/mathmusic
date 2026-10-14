<!-- The selected track's sound (waveform, instrument or formula), envelope and mix settings. -->
<script lang="ts">
  import { daw } from "$lib/daw.svelte";
  import type { Track } from "$lib/types";
  import Check from "./fields/Check.svelte";
  import Errors from "./fields/Errors.svelte";
  import Field from "./fields/Field.svelte";
  import NumberField from "./fields/NumberField.svelte";
  import TextField from "./fields/TextField.svelte";
  import FormulaPlot from "./FormulaPlot.svelte";

  const DEFAULT_CYCLE = ["sine", "triangle", "saw", "square"];

  const track = $derived(daw.selectedTrack);
  const index = $derived(track ? daw.project.tracks.indexOf(track) : 0);

  function isNamed(spec: string | null): boolean {
    const cat = daw.catalogue;
    return !spec || cat.waveforms.some((w) => w.name === spec) || cat.instruments.some((i) => i.name === spec);
  }

  /** The formulas behind a track's sound, for plotting. */
  function formulas(t: Track): { wave: string; envelope: string | null } {
    const cat = daw.catalogue;
    const name = t.sound || DEFAULT_CYCLE[index % DEFAULT_CYCLE.length];
    const wave = cat.waveforms.find((w) => w.name === name);
    if (wave) return { wave: wave.formula, envelope: null };
    const inst = cat.instruments.find((i) => i.name === name);
    if (inst) return { wave: inst.wave, envelope: inst.envelope };
    return { wave: t.sound ?? "", envelope: null };
  }

  const sound = $derived(track ? formulas(track) : null);
  const choice = $derived(
    track ? (track.sound === null ? "auto" : isNamed(track.sound) ? track.sound : "__custom__") : "auto",
  );
  const instrument = $derived(daw.catalogue.instruments.find((i) => i.name === track?.sound));

  function chooseSound(value: string) {
    if (!track) return;
    const t = track;
    daw.edit(() => {
      if (value === "__custom__") t.sound = isNamed(t.sound) ? "sin(2*pi*x) + 0.3*sin(6*pi*x)" : t.sound;
      else t.sound = value === "auto" ? null : value;
    });
  }

  function move(delta: number) {
    if (!track) return;
    const t = track;
    daw.edit((p) => {
      const from = p.tracks.indexOf(t);
      const to = from + delta;
      if (to < 0 || to >= p.tracks.length) return;
      [p.tracks[from], p.tracks[to]] = [p.tracks[to], p.tracks[from]];
    });
  }
</script>

{#if !track}
  <p class="py-6 text-muted">Select a track to edit its sound.</p>
{:else}
  <div class="grid grid-cols-[minmax(300px,420px)_1fr] gap-4.5 max-[900px]:grid-cols-1">
    <div>
      <TextField label="Name" value={track.name} mono={false} maxlength={80} onlive={(v) => (track.name = v)} />
      <Field label="Sound">
        <select class="input w-full" value={choice} onchange={(e) => chooseSound(e.currentTarget.value)}>
          <option value="auto">auto (by track number)</option>
          <optgroup label="Waveforms">
            {#each daw.catalogue.waveforms as w (w.name)}<option value={w.name}>{w.name}</option>{/each}
          </optgroup>
          <optgroup label="Instruments">
            {#each daw.catalogue.instruments as i (i.name)}<option value={i.name} title={i.description}>{i.name}</option
              >{/each}
          </optgroup>
          <option value="__custom__">custom formula…</option>
        </select>
      </Field>
      {#if choice === "__custom__"}
        <TextField
          value={track.sound}
          placeholder="one cycle in x, e.g. sin(2*pi*x) + 0.3*sin(6*pi*x)"
          onlive={(v) => (track.sound = v)}
        />
      {/if}
      {#if instrument}<p class="hint mb-2">{instrument.description}</p>{/if}
      <Errors errors={daw.errorsFor(track.id, null).filter((e) => e.field === "sound")} />
      <TextField
        label="Envelope over each note (x = 0 at the start, 1 at the end)"
        value={track.envelope}
        placeholder="instrument default; e.g. exp(-4*x) or min(1, 20*x)"
        onlive={(v) => (track.envelope = v.trim() ? v : null)}
      />
      <div class="grid grid-cols-2 gap-x-3">
        <NumberField
          label="Volume (dB)"
          value={track.volume_db}
          min={-60}
          max={12}
          step={0.5}
          onlive={(v) => (track.volume_db = v)}
        />
        <NumberField
          label="Pan (−1 left … 1 right)"
          value={track.pan}
          min={-1}
          max={1}
          step={0.05}
          onlive={(v) => (track.pan = v)}
        />
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <Check label="Mute" checked={track.mute} onchange={(v) => (track.mute = v)} />
        <Check label="Solo" checked={track.solo} onchange={(v) => (track.solo = v)} />
        <span class="flex-1"></span>
        <button class="btn sm" type="button" disabled={index === 0} onclick={() => move(-1)}>Move up</button>
        <button class="btn sm" type="button" disabled={index === daw.project.tracks.length - 1} onclick={() => move(1)}
          >Move down</button
        >
      </div>
    </div>
    <div class="flex min-w-0 flex-col gap-3">
      <div>
        <div class="mb-1 text-[11px] tracking-widest text-muted uppercase">Waveform: one cycle</div>
        <FormulaPlot formula={sound?.wave ?? ""} start={0} end={1} xLabel="phase" class="h-[130px]" label="Waveform" />
      </div>
      <div>
        <div class="mb-1 text-[11px] tracking-widest text-muted uppercase">Envelope: one note</div>
        <FormulaPlot
          formula={track.envelope || sound?.envelope || ""}
          fallback="1"
          start={0}
          end={1}
          stroke="#a855f7"
          xLabel="note"
          class="h-[130px]"
          label="Envelope"
        />
      </div>
    </div>
  </div>
{/if}
