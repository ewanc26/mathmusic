<!-- A slider edited live; optionally logarithmic (e.g. filter cutoff). -->
<script lang="ts">
  import { daw } from "$lib/daw.svelte";
  import Field from "./Field.svelte";

  interface Props {
    label: string;
    value: number;
    onlive: (value: number) => void;
    min: number;
    max: number;
    step?: number;
    log?: boolean;
    format?: (value: number) => string;
    ondouble?: () => void;
  }

  let { label, value, onlive, min, max, step, log = false, format = (v) => v.toFixed(2), ondouble }: Props = $props();

  const toSlider = (v: number) => (log ? Math.log(v) : v);
  const fromSlider = (v: number) => (log ? Math.round(Math.exp(v)) : Number(v.toFixed(4)));
  const sliderStep = $derived(step ?? (log ? 0.001 : (max - min) / 400));
</script>

<Field {label}>
  <span class="flex items-center gap-2">
    <input
      class="min-w-0 flex-1"
      type="range"
      min={toSlider(min)}
      max={toSlider(max)}
      step={sliderStep}
      value={toSlider(value)}
      oninput={(e) => daw.live(() => onlive(fromSlider(Number(e.currentTarget.value))))}
      onchange={daw.settle}
      ondblclick={ondouble}
    />
    <output class="readout w-[76px] text-right">{format(value)}</output>
  </span>
</Field>
