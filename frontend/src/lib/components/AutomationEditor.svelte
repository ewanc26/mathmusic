<!-- Gain and pan automation for the selected track: formulas of the beat, plotted over the song. -->
<script lang="ts">
  import { daw } from "$lib/daw.svelte";
  import { transport } from "$lib/transport.svelte";
  import type { Automation } from "$lib/types";
  import Errors from "./fields/Errors.svelte";
  import TextField from "./fields/TextField.svelte";
  import FormulaPlot from "./FormulaPlot.svelte";

  const EXAMPLES: Record<keyof Automation, [string, string][]> = {
    gain: [
      ["fade in", "min(1, x/8)"],
      ["fade out", "max(0, 1 - x/32)"],
      ["swell", "0.6 + 0.4*sin(2*pi*x/16)"],
      ["tremolo", "0.7 + 0.3*sin(2*pi*x*2)"],
      ["gate", "(sign(sin(pi*x)) + 1)/2"],
    ],
    pan: [
      ["auto-pan", "sin(2*pi*x/8)"],
      ["slow sweep", "sin(2*pi*x/32)"],
      ["ping-pong", "sign(sin(pi*x))*0.8"],
    ],
  };

  const LANES: { key: keyof Automation; label: string; stroke: string; hint: string; fallback: string }[] = [
    {
      key: "gain",
      label: "Gain × f(x)",
      stroke: "#34d399",
      hint: "x is the song position in beats; the result multiplies the volume (0 to 4).",
      fallback: "1",
    },
    {
      key: "pan",
      label: "Pan + f(x)",
      stroke: "#60a5fa",
      hint: "added to the track's pan and clipped to −1 … 1.",
      fallback: "0",
    },
  ];

  const track = $derived(daw.selectedTrack);
  const marker = $derived(transport.hasAudio && (transport.playing || transport.beat > 0) ? transport.beat : null);
</script>

{#if !track}
  <p class="py-6 text-muted">Select a track to automate it.</p>
{:else}
  <p class="hint mb-3">
    Automate effect parameters too: press ƒ next to a cutoff, Q, feedback or mix in the Effects tab.
  </p>
  <div class="grid grid-cols-2 gap-4.5 max-[900px]:grid-cols-1">
    {#each LANES as lane (lane.key)}
      <div>
        <TextField
          label={lane.label}
          hint={lane.hint}
          value={track.automation[lane.key]}
          placeholder={lane.key === "gain" ? "e.g. min(1, x/8)  (empty: no automation)" : "e.g. sin(2*pi*x/8)"}
          onlive={(v) => (track.automation[lane.key] = v.trim() ? v : null)}
        />
        <div class="mb-2 flex flex-wrap gap-1.5">
          {#each EXAMPLES[lane.key] as [name, formula] (name)}
            <button
              class="chip"
              type="button"
              title={formula}
              onclick={() => daw.edit(() => (track.automation[lane.key] = formula))}
            >
              {name}
            </button>
          {/each}
          <button class="chip" type="button" onclick={() => daw.edit(() => (track.automation[lane.key] = null))}
            >clear</button
          >
        </div>
        <Errors errors={daw.errorsFor(track.id, null).filter((e) => e.field === `automation.${lane.key}`)} />
        <FormulaPlot
          formula={track.automation[lane.key]}
          fallback={lane.fallback}
          start={0}
          end={daw.songLength}
          stroke={lane.stroke}
          xLabel="beat"
          {marker}
          points={400}
          class="h-[150px]"
          label="{lane.key} automation"
        />
      </div>
    {/each}
  </div>
{/if}
