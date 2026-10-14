<!-- y = f(x) for any formula, sampled by the server and drawn live while it is edited. -->
<script lang="ts">
  import { plot } from "$lib/api";
  import { drawFormula, drawMessage } from "$lib/draw";
  import type { PlotData } from "$lib/types";
  import Canvas from "./Canvas.svelte";

  interface Props {
    formula: string | null;
    start: number;
    end: number;
    stroke?: string;
    xLabel?: string;
    yRange?: [number, number] | null;
    fallback?: string;
    marker?: number | null;
    points?: number;
    class?: string;
    label?: string;
  }

  let {
    formula,
    start,
    end,
    stroke = "#25f4ee",
    xLabel = "x",
    yRange = null,
    fallback = "",
    marker = null,
    points = 240,
    class: className = "",
    label = "Graph",
  }: Props = $props();

  let data = $state.raw<PlotData | null>(null);
  let error = $state("");
  let seq = 0;

  const text = $derived((formula ?? "").trim() || fallback);

  $effect(() => {
    const mine = ++seq;
    if (!text) {
      data = null;
      error = "";
      return;
    }
    plot(text, start, end, points)
      .then((result) => {
        if (mine !== seq) return;
        data = result;
        error = "";
      })
      .catch((e: Error) => {
        if (mine !== seq) return;
        error = e.message;
      });
  });

  function draw(canvas: HTMLCanvasElement) {
    if (error) drawMessage(canvas, error, "bad");
    else if (!text) drawMessage(canvas, "no formula");
    else if (data) drawFormula(canvas, data, { stroke, xLabel, yRange, marker });
  }
</script>

<Canvas {draw} class="panel-canvas {className}" aria-label={label} />
