<!--
  The arrangement: a beat ruler and one lane per track. Curve clips are drawn as
  their curves, audio clips as their waveforms; each lane also shows the track's
  rendered level and its automation. Clips can be moved (also between tracks),
  resized and created; audio files can be imported or dropped onto a lane.
-->
<script lang="ts">
  import { FileAudio, Maximize2, Minus, Plus } from "@lucide/svelte";
  import { SvelteMap } from "svelte/reactivity";
  import { addTrack, importAudio } from "$lib/actions.svelte";
  import { plot } from "$lib/api";
  import { daw, newClip, newTrack } from "$lib/daw.svelte";
  import { transport } from "$lib/transport.svelte";
  import type { Clip, PlotData, Track } from "$lib/types";
  import { clamp, color, prepareCanvas, trackColor } from "$lib/util";
  import { TRACK_HEIGHT, view } from "$lib/view.svelte";
  import Canvas from "./Canvas.svelte";
  import TrackHeader from "./TrackHeader.svelte";

  const EDGE_PX = 7;

  let wrap = $state<HTMLDivElement>();
  let lanes = $state<HTMLCanvasElement>();
  let ruler = $state<HTMLCanvasElement>();
  let fileInput = $state<HTMLInputElement>();
  let scrollTop = $state(0);
  let wrapHeight = $state(300);

  $effect(() => {
    if (!wrap) return;
    const element = wrap;
    const observer = new ResizeObserver(() => {
      view.width = element.clientWidth;
      wrapHeight = element.clientHeight;
    });
    observer.observe(element);
    return () => observer.disconnect();
  });

  const playhead = $derived(transport.hasAudio ? transport.beat : null);
  const lanesHeight = $derived(Math.max(daw.project.tracks.length * TRACK_HEIGHT, wrapHeight));
  const snap = $derived(view.snap(daw.project.beats_per_bar));
  const snapBeat = (beat: number) => Math.round(beat / snap) * snap;

  $effect(() => {
    if (transport.playing && playhead !== null) view.follow(playhead);
  });

  // ---------------------------------------------------------------- automation curves

  const automationCurves = new SvelteMap<string, PlotData | null>();

  function automationCurve(formula: string, length: number): PlotData | null {
    const key = `${formula}|${length}`;
    if (automationCurves.has(key)) return automationCurves.get(key) ?? null;
    automationCurves.set(key, null);
    plot(formula, 0, length, 400)
      .then((data) => automationCurves.set(key, data))
      .catch(() => automationCurves.set(key, { x: [], y: [] }));
    return null;
  }

  // ---------------------------------------------------------------- drawing

  function drawRuler(canvas: HTMLCanvasElement) {
    const { ctx, h } = prepareCanvas(canvas);
    const p = daw.project;
    const bar = p.beats_per_bar;
    const muted = color("muted", "#8f8f98");
    const x0 = view.beatToX(p.loop_start);
    const x1 = view.beatToX(p.loop_end);
    ctx.fillStyle = color("accent", "#fe2c55");
    ctx.globalAlpha = p.loop_enabled ? 0.55 : 0.18;
    ctx.fillRect(x0, h - 7, x1 - x0, 5);
    ctx.globalAlpha = 1;

    ctx.font = "11px 'JetBrains Mono', ui-monospace, monospace";
    ctx.fillStyle = muted;
    ctx.strokeStyle = muted;
    const barEvery = view.pxPerBeat * bar < 28 ? Math.ceil(28 / (view.pxPerBeat * bar)) : 1;
    const first = Math.floor(view.scroll);
    const last = Math.ceil(view.scroll + view.visibleBeats());
    for (let b = first; b <= last; b++) {
      const x = Math.round(view.beatToX(b)) + 0.5;
      if (b % bar === 0) {
        if ((b / bar) % barEvery === 0) {
          ctx.fillText(String(b / bar + 1), x + 3, 12);
          ctx.beginPath();
          ctx.moveTo(x, 2);
          ctx.lineTo(x, h);
          ctx.stroke();
        }
      } else if (view.pxPerBeat >= 8) {
        ctx.beginPath();
        ctx.moveTo(x, h - 6);
        ctx.lineTo(x, h);
        ctx.stroke();
      }
    }
    if (playhead !== null) {
      const x = view.beatToX(playhead);
      ctx.fillStyle = "#ffffff";
      ctx.beginPath();
      ctx.moveTo(x - 5, h - 10);
      ctx.lineTo(x + 5, h - 10);
      ctx.lineTo(x, h - 2);
      ctx.fill();
    }
  }

  function drawTrackPeaks(ctx: CanvasRenderingContext2D, peaks: number[], top: number, stroke: string) {
    const perBeat = daw.render?.peaks_per_beat ?? 8;
    if (!peaks.length) return;
    const mid = top + TRACK_HEIGHT / 2;
    const half = TRACK_HEIGHT / 2 - 6;
    const first = Math.max(0, Math.floor(view.scroll * perBeat));
    const last = Math.min(peaks.length - 1, Math.ceil((view.scroll + view.visibleBeats()) * perBeat));
    const width = Math.max(1, view.pxPerBeat / perBeat);
    ctx.fillStyle = stroke;
    ctx.globalAlpha = 0.13;
    for (let i = first; i <= last; i++) {
      const amplitude = Math.min(1, peaks[i]) * half;
      if (amplitude >= 0.5) ctx.fillRect(view.beatToX(i / perBeat), mid - amplitude, width, amplitude * 2);
    }
    ctx.globalAlpha = 1;
  }

  function drawClip(ctx: CanvasRenderingContext2D, clip: Clip, stroke: string, top: number, audible: boolean) {
    const x0 = view.beatToX(clip.start);
    const x1 = view.beatToX(clip.start + clip.length);
    if (x1 < 0 || x0 > view.width) return;
    const selected = clip.id === daw.selection.clip;
    const y0 = top + 4;
    const height = TRACK_HEIGHT - 8;
    const width = Math.max(4, x1 - x0 - 1);
    const data = daw.clipRender(clip.id);
    const failed = Boolean(data?.error);
    const alpha = audible ? 1 : 0.35;

    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.beginPath();
    ctx.roundRect(x0 + 0.5, y0 + 0.5, width, height, 6);
    ctx.fillStyle = stroke;
    ctx.globalAlpha = alpha * (clip.kind === "audio" ? 0.24 : 0.16);
    ctx.fill();
    ctx.globalAlpha = alpha;
    ctx.lineWidth = selected ? 2 : 1;
    ctx.strokeStyle = failed ? color("bad", "#ff5d6c") : selected ? "#ffffff" : stroke;
    ctx.stroke();
    ctx.clip();

    ctx.font = "11px 'JetBrains Mono', ui-monospace, monospace";
    ctx.fillStyle = failed ? color("bad", "#ff5d6c") : color("ink", "#fff");
    const label = clip.kind === "audio" ? `♪ ${clip.name || "audio"}` : clip.name || `y = ${clip.expression}`;
    ctx.fillText(`${failed ? "⚠ " : ""}${label}`, x0 + 6, y0 + 13);

    const plotTop = y0 + 18;
    const plotH = height - 24;
    if (data?.kind === "audio") {
      // the sample's level, PEAKS_PER_BEAT buckets per beat from the clip start
      const perBeat = daw.render?.peaks_per_beat ?? 8;
      const mid = plotTop + plotH / 2;
      ctx.fillStyle = stroke;
      ctx.globalAlpha = alpha * 0.8;
      const bucket = Math.max(1, view.pxPerBeat / perBeat);
      data.peaks.forEach((peak, i) => {
        const amplitude = Math.max(0.5, Math.min(1, peak) * (plotH / 2));
        ctx.fillRect(view.beatToX(clip.start + i / perBeat), mid - amplitude, bucket, amplitude * 2);
      });
    } else if (data?.kind === "curve") {
      const samples = data.samples;
      const [lo, hi] = data.bounds ?? [0, 1];
      const span = hi - lo || 1;
      const toY = (y: number) => plotTop + (1 - clamp((y - lo) / span, 0, 1)) * plotH;
      ctx.strokeStyle = stroke;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      let pen = false;
      for (const s of samples) {
        if (s.y === null) {
          pen = false;
          continue;
        }
        const px = view.beatToX(s.start + s.duration / 2);
        if (pen) ctx.lineTo(px, toY(s.y));
        else ctx.moveTo(px, toY(s.y));
        pen = true;
      }
      ctx.stroke();
      if ((view.pxPerBeat * clip.length) / Math.max(samples.length, 1) > 5) {
        ctx.fillStyle = stroke;
        for (const s of samples) {
          if (s.y !== null) ctx.fillRect(view.beatToX(s.start + s.duration / 2) - 1.5, toY(s.y) - 1.5, 3, 3);
        }
      }
    }
    if (selected) {
      ctx.fillStyle = "#ffffff";
      ctx.globalAlpha = 0.5;
      ctx.fillRect(x0 + width - 4, y0 + height / 2 - 8, 2, 16);
    }
    ctx.restore();
  }

  function drawAutomation(ctx: CanvasRenderingContext2D, track: Track, top: number) {
    const length = daw.songLength;
    const curves: [keyof Track["automation"], string, (v: number) => number][] = [
      [
        "gain",
        color("neon-green", "#34d399"),
        (v) => top + TRACK_HEIGHT - 5 - (clamp(v, 0, 1.5) / 1.5) * (TRACK_HEIGHT - 10),
      ],
      ["pan", color("neon-blue", "#60a5fa"), (v) => top + TRACK_HEIGHT / 2 - clamp(v, -1, 1) * (TRACK_HEIGHT / 2 - 6)],
    ];
    for (const [key, stroke, toY] of curves) {
      const formula = track.automation[key];
      if (!formula) continue;
      const data = automationCurve(formula, length);
      if (!data?.x.length) continue;
      ctx.strokeStyle = stroke;
      ctx.globalAlpha = 0.75;
      ctx.lineWidth = 1.25;
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      let pen = false;
      data.x.forEach((x, i) => {
        const y = data.y[i];
        if (y === null) {
          pen = false;
          return;
        }
        if (pen) ctx.lineTo(view.beatToX(x), toY(y));
        else ctx.moveTo(view.beatToX(x), toY(y));
        pen = true;
      });
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
    }
  }

  function drawLanes(canvas: HTMLCanvasElement) {
    const { ctx, w, h } = prepareCanvas(canvas);
    const p = daw.project;
    const line = color("line", "#2b2b2e");

    p.tracks.forEach((track, i) => {
      const top = i * TRACK_HEIGHT;
      ctx.fillStyle =
        track.id === daw.selection.track ? color("panel-2", "#18181b") : i % 2 ? color("panel", "#0e0e10") : "#000";
      ctx.fillRect(0, top, w, TRACK_HEIGHT);
      ctx.fillStyle = line;
      ctx.fillRect(0, top + TRACK_HEIGHT - 1, w, 1);
    });

    // beat and bar grid
    const bar = p.beats_per_bar;
    for (let b = Math.floor(view.scroll); b <= Math.ceil(view.scroll + view.visibleBeats()); b++) {
      const isBar = b % bar === 0;
      if (!isBar && view.pxPerBeat < 8) continue;
      ctx.strokeStyle = line;
      ctx.globalAlpha = isBar ? 0.9 : 0.35;
      ctx.beginPath();
      ctx.moveTo(Math.round(view.beatToX(b)) + 0.5, 0);
      ctx.lineTo(Math.round(view.beatToX(b)) + 0.5, h);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;

    // loop region
    ctx.fillStyle = color("accent", "#fe2c55");
    ctx.globalAlpha = p.loop_enabled ? 0.1 : 0.04;
    ctx.fillRect(view.beatToX(p.loop_start), 0, (p.loop_end - p.loop_start) * view.pxPerBeat, h);
    ctx.globalAlpha = 1;

    p.tracks.forEach((track, i) => {
      const info = daw.trackRender(track.id);
      const stroke = trackColor(i);
      drawTrackPeaks(ctx, info?.peaks ?? [], i * TRACK_HEIGHT, stroke);
      for (const clip of track.clips) drawClip(ctx, clip, stroke, i * TRACK_HEIGHT, info?.audible ?? true);
      drawAutomation(ctx, track, i * TRACK_HEIGHT);
    });

    if (!p.tracks.length) {
      ctx.fillStyle = color("muted", "#8f8f98");
      ctx.font = "13px sans-serif";
      ctx.fillText("Add a track to start. Double-click a lane to add a clip, or drop an audio file here.", 16, 28);
    }

    if (playhead !== null) {
      const x = Math.round(view.beatToX(playhead)) + 0.5;
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }
  }

  // ---------------------------------------------------------------- interaction

  type Drag = { mode: "move" | "resize"; clipId: string; startX: number; origStart: number; origLength: number };
  let drag: Drag | null = null;
  let rulerDrag: { x: number; beat: number; moved: boolean } | null = null;
  let cursor = $state("default");
  let dropping = $state(false);

  function local(event: MouseEvent, canvas: HTMLCanvasElement | undefined) {
    const rect = canvas?.getBoundingClientRect();
    return { x: event.clientX - (rect?.left ?? 0), y: event.clientY - (rect?.top ?? 0) };
  }

  function hitTest(x: number, y: number) {
    const index = Math.floor(y / TRACK_HEIGHT);
    const track = daw.project.tracks[index] ?? null;
    if (!track) return { track: null, clip: null, edge: false };
    for (let i = track.clips.length - 1; i >= 0; i--) {
      const clip = track.clips[i];
      const x0 = view.beatToX(clip.start);
      const x1 = view.beatToX(clip.start + clip.length);
      if (x >= x0 && x <= x1) return { track, clip, edge: x >= x1 - EDGE_PX };
    }
    return { track, clip: null, edge: false };
  }

  function lanesDown(event: MouseEvent) {
    if (event.button !== 0) return;
    const { x, y } = local(event, lanes);
    const hit = hitTest(x, y);
    daw.select(hit.track?.id ?? null, hit.clip?.id ?? null);
    if (!hit.clip) return;
    drag = {
      mode: hit.edge ? "resize" : "move",
      clipId: hit.clip.id,
      startX: event.clientX,
      origStart: hit.clip.start,
      origLength: hit.clip.length,
    };
    cursor = "grabbing";
    event.preventDefault();
  }

  function windowMove(event: MouseEvent) {
    if (drag) {
      const delta = (event.clientX - drag.startX) / view.pxPerBeat;
      const found = daw.clip(drag.clipId);
      if (!found) return;
      if (drag.mode === "resize") {
        const length = Math.max(snap, snapBeat(drag.origLength + delta));
        if (length !== found.clip.length) daw.live(() => (found.clip.length = length));
        return;
      }
      const start = Math.max(0, snapBeat(drag.origStart + delta));
      const tracks = daw.project.tracks;
      const target = tracks[clamp(Math.floor(local(event, lanes).y / TRACK_HEIGHT), 0, tracks.length - 1)];
      if (start === found.clip.start && target.id === found.track.id) return;
      daw.live(() => {
        found.clip.start = start;
        if (target.id !== found.track.id) {
          const moved = found.track.clips.splice(found.track.clips.indexOf(found.clip), 1)[0];
          target.clips.push(moved);
          daw.selection.track = target.id;
        }
      });
      return;
    }
    if (rulerDrag) {
      const { x } = local(event, ruler);
      if (Math.abs(x - rulerDrag.x) < 4 && !rulerDrag.moved) return;
      rulerDrag.moved = true;
      const a = snapBeat(rulerDrag.beat);
      const b = snapBeat(Math.max(0, view.xToBeat(x)));
      const start = Math.min(a, b);
      const end = Math.max(a, b, start + snap);
      daw.live((p) => {
        p.loop_start = start;
        p.loop_end = end;
        p.loop_enabled = true;
      });
    }
  }

  function windowUp() {
    if (drag) {
      drag = null;
      cursor = "default";
      daw.settle();
    }
    if (rulerDrag) {
      if (!rulerDrag.moved) transport.seekBeat(rulerDrag.beat);
      else daw.settle();
      rulerDrag = null;
    }
  }

  function lanesHover(event: MouseEvent) {
    if (drag) return;
    const { x, y } = local(event, lanes);
    const hit = hitTest(x, y);
    cursor = hit.clip ? (hit.edge ? "ew-resize" : "grab") : "default";
  }

  let { onfocusclip }: { onfocusclip: () => void } = $props();

  function lanesDouble(event: MouseEvent) {
    const { x, y } = local(event, lanes);
    const hit = hitTest(x, y);
    if (hit.clip) {
      onfocusclip();
      return;
    }
    const start = Math.max(0, Math.floor(view.xToBeat(x) / snap) * snap);
    const clip = newClip(start);
    const existing = hit.track;
    if (existing) {
      daw.edit(() => existing.clips.push(clip));
      daw.select(existing.id, clip.id);
    } else {
      const track = newTrack(daw.project.tracks.length);
      track.clips.push(clip);
      daw.edit((p) => p.tracks.push(track));
      daw.select(track.id, clip.id);
    }
    onfocusclip();
  }

  function wheel(event: WheelEvent) {
    if (event.ctrlKey || event.metaKey) {
      event.preventDefault();
      view.zoomAt(Math.exp(-event.deltaY * 0.01), local(event, lanes).x);
      return;
    }
    const horizontal = event.shiftKey ? event.deltaY : event.deltaX;
    if (Math.abs(horizontal) > Math.abs(event.shiftKey ? 0 : event.deltaY)) {
      event.preventDefault();
      view.scroll = Math.max(0, view.scroll + horizontal / view.pxPerBeat);
    }
  }

  // wheel listeners must not be passive, or zooming would also scroll the page
  $effect(() => {
    const targets = [lanes, ruler].filter((t): t is HTMLCanvasElement => Boolean(t));
    for (const target of targets) target.addEventListener("wheel", wheel, { passive: false });
    return () => targets.forEach((target) => target.removeEventListener("wheel", wheel));
  });

  function drop(event: DragEvent) {
    event.preventDefault();
    dropping = false;
    const file = event.dataTransfer?.files[0];
    if (!file) return;
    const { y } = local(event, lanes);
    const track = daw.project.tracks[Math.floor(y / TRACK_HEIGHT)];
    if (track) daw.select(track.id, null);
    void importAudio(file);
  }
</script>

<svelte:window onmousemove={windowMove} onmouseup={windowUp} />

<section class="grid min-h-0 grid-rows-[auto_1fr_auto] border-b border-line" aria-label="Arrangement">
  <div class="grid grid-cols-[240px_1fr] border-b border-line max-[900px]:grid-cols-[170px_1fr]">
    <div class="flex items-center gap-1.5 border-r border-line px-2 py-1">
      <button class="btn sm" type="button" title="Add track (T)" onclick={addTrack}>+ Track</button>
      <button
        class="btn sm"
        type="button"
        title="Import an audio file onto the selected track"
        onclick={() => fileInput?.click()}
      >
        <FileAudio size={13} /> Audio
      </button>
      <input
        bind:this={fileInput}
        class="hidden"
        type="file"
        accept="audio/*,.wav,.mp3,.flac,.ogg,.aiff,.m4a"
        onchange={(e) => {
          const file = e.currentTarget.files?.[0];
          if (file) void importAudio(file);
          e.currentTarget.value = "";
        }}
      />
      <label class="inline-flex items-center gap-1 text-[11px] text-muted">
        Snap
        <select
          class="input py-0.5 text-xs"
          value={String(view.snapSetting)}
          onchange={(e) => (view.snapSetting = Number(e.currentTarget.value))}
        >
          <option value="0.25">1/16</option>
          <option value="0.5">1/8</option>
          <option value="1">beat</option>
          <option value="0">bar</option>
        </select>
      </label>
      <span class="ml-auto inline-flex gap-0.5">
        <button
          class="icon-btn sm"
          type="button"
          title="Zoom out (−)"
          aria-label="Zoom out"
          onclick={() => view.zoomAt(1 / 1.4)}><Minus size={12} /></button
        >
        <button
          class="icon-btn sm"
          type="button"
          title="Fit (F)"
          aria-label="Zoom to fit"
          onclick={() => view.fit(daw.songLength)}><Maximize2 size={11} /></button
        >
        <button
          class="icon-btn sm"
          type="button"
          title="Zoom in (+)"
          aria-label="Zoom in"
          onclick={() => view.zoomAt(1.4)}><Plus size={12} /></button
        >
      </span>
    </div>
    <Canvas
      bind:element={ruler}
      draw={drawRuler}
      class="block h-[34px] w-full cursor-pointer bg-panel"
      aria-label="Timeline ruler: click to seek, drag to set the loop"
      onmousedown={(event: MouseEvent) => {
        if (event.button !== 0) return;
        const { x } = local(event, ruler);
        rulerDrag = { x, beat: Math.max(0, view.xToBeat(x)), moved: false };
      }}
    />
  </div>

  <div class="grid min-h-0 grid-cols-[240px_1fr] max-[900px]:grid-cols-[170px_1fr]">
    <div class="overflow-hidden border-r border-line bg-panel">
      <div style="transform: translateY({-scrollTop}px)">
        {#each daw.project.tracks as track, index (track.id)}
          <TrackHeader {track} {index} />
        {/each}
      </div>
    </div>
    <div
      bind:this={wrap}
      class="min-h-0 overflow-x-hidden overflow-y-auto"
      class:outline-2={dropping}
      class:outline-neon-cyan={dropping}
      onscroll={(e) => (scrollTop = e.currentTarget.scrollTop)}
      ondragover={(e) => {
        e.preventDefault();
        dropping = true;
      }}
      ondragleave={() => (dropping = false)}
      ondrop={drop}
      role="presentation"
    >
      <Canvas
        bind:element={lanes}
        draw={drawLanes}
        class="block w-full"
        style="height: {lanesHeight}px; cursor: {cursor}"
        aria-label="Track lanes: drag clips to move them, drag their right edge to resize, double-click to add a clip"
        onmousedown={lanesDown}
        onmousemove={lanesHover}
        ondblclick={lanesDouble}
      />
    </div>
  </div>

  <div class="min-h-[22px] border-t border-line px-2.5 py-0.5 font-mono text-[11px]">
    {#if daw.rendering}
      <span class="text-muted">rendering…</span>
    {:else if daw.renderError}
      <span class="text-bad">not rendered: {daw.renderError}</span>
    {:else if daw.render?.errors.length}
      <span class="text-bad">
        {daw.render.errors.length} formula issue{daw.render.errors.length === 1 ? "" : "s"} (see the highlighted clips and
        fields)
      </span>
    {:else if daw.render}
      <span class="text-muted">{daw.render.duration.toFixed(1)} s rendered</span>
    {/if}
  </div>
</section>
