<!-- Master volume, normalisation, loop region and the master effects chain. -->
<script lang="ts">
  import { daw } from "$lib/daw.svelte";
  import EffectChain from "./EffectChain.svelte";
  import Check from "./fields/Check.svelte";
  import NumberField from "./fields/NumberField.svelte";
  import RangeField from "./fields/RangeField.svelte";
</script>

<div class="grid grid-cols-[minmax(300px,420px)_1fr] gap-4.5 max-[900px]:grid-cols-1">
  <div>
    <RangeField
      label="Master volume (dB)"
      value={daw.project.master.volume_db}
      min={-60}
      max={12}
      step={0.5}
      format={(v) => `${v.toFixed(1)} dB`}
      onlive={(v) => (daw.project.master.volume_db = v)}
    />
    <Check
      label="Normalise the mix to −1 dBFS"
      checked={daw.project.master.normalize}
      onchange={(v) => (daw.project.master.normalize = v)}
    />
    <div class="grid grid-cols-2 gap-x-3">
      <NumberField
        label="Loop start (beat)"
        value={daw.project.loop_start}
        min={0}
        max={2048}
        onlive={(v) => (daw.project.loop_start = v)}
      />
      <NumberField
        label="Loop end (beat)"
        value={daw.project.loop_end}
        min={0.25}
        max={2048}
        onlive={(v) => (daw.project.loop_end = v)}
      />
    </div>
    <Check
      label="Loop playback (L)"
      checked={daw.project.loop_enabled}
      onchange={(v) => (daw.project.loop_enabled = v)}
    />
    {#if daw.render}
      <p class="hint">
        Length {daw.render.length_beats} beats · {daw.render.duration.toFixed(1)} s, including a 3 s tail for reverb and delay.
      </p>
    {/if}
  </div>
  <div>
    <h3 class="mb-2.5 text-xs tracking-widest text-muted uppercase">Master effects</h3>
    <EffectChain chain={daw.project.master.effects} errors={daw.errorsFor(null, null)} />
  </div>
</div>
