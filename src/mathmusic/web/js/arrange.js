// The arrangement: a beat ruler and one lane per track, with clips drawn as
// their curves. Clips can be moved (also between tracks), resized and created.

import {
  clipRender,
  edit,
  emit,
  findClip,
  live,
  newClip,
  newTrack,
  select,
  settle,
  state,
} from "./store.js";
import { plot } from "./api.js";
import { seekBeat } from "./transport.js";
import { PALETTE, clamp, cssVar, prepareCanvas } from "./util.js";

export const TRACK_H = 72;
const EDGE_PX = 7;
const MIN_PX_PER_BEAT = 3;
const MAX_PX_PER_BEAT = 160;

export const view = { pxPerBeat: 20, scroll: 0, snap: 1 };

let ruler;
let lanes;
let wrap;
let drag = null;
let rulerDrag = null;

const beatToX = (beat) => (beat - view.scroll) * view.pxPerBeat;
const xToBeat = (x) => x / view.pxPerBeat + view.scroll;
const snapBeat = (beat) => Math.round(beat / view.snap) * view.snap;
export const trackColor = (index) => PALETTE[index % PALETTE.length];

function visibleBeats() {
  return lanes.clientWidth / view.pxPerBeat;
}

function local(event, canvas) {
  const rect = canvas.getBoundingClientRect();
  return { x: event.clientX - rect.left, y: event.clientY - rect.top };
}

// ---------------------------------------------------------------- drawing

function drawGrid(ctx, w, h, top = 0) {
  const line = cssVar("--line", "#2b2b2e");
  const first = Math.floor(view.scroll);
  const last = Math.ceil(view.scroll + visibleBeats());
  const showBeats = view.pxPerBeat >= 8;
  ctx.lineWidth = 1;
  for (let beat = first; beat <= last; beat++) {
    const isBar = beat % 4 === 0;
    if (!isBar && !showBeats) continue;
    const x = Math.round(beatToX(beat)) + 0.5;
    ctx.strokeStyle = line;
    ctx.globalAlpha = isBar ? 0.9 : 0.35;
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, h);
    ctx.stroke();
  }
  ctx.globalAlpha = 1;
}

function drawLoop(ctx, h, top = 0) {
  const p = state.project;
  const x0 = beatToX(p.loop_start);
  const x1 = beatToX(p.loop_end);
  ctx.fillStyle = cssVar("--accent", "#fe2c55");
  ctx.globalAlpha = p.loop_enabled ? 0.1 : 0.04;
  ctx.fillRect(x0, top, x1 - x0, h - top);
  ctx.globalAlpha = 1;
}

export function drawRuler(beat) {
  const { ctx, w, h } = prepareCanvas(ruler);
  const p = state.project;
  if (!p) return;
  const muted = cssVar("--muted", "#8f8f98");
  const accent = cssVar("--accent", "#fe2c55");

  // loop region band
  const x0 = beatToX(p.loop_start);
  const x1 = beatToX(p.loop_end);
  ctx.fillStyle = accent;
  ctx.globalAlpha = p.loop_enabled ? 0.55 : 0.18;
  ctx.fillRect(x0, h - 7, x1 - x0, 5);
  ctx.globalAlpha = 1;

  ctx.font = "11px ui-monospace, Menlo, monospace";
  ctx.fillStyle = muted;
  ctx.strokeStyle = muted;
  const barEvery = view.pxPerBeat * 4 < 28 ? Math.ceil(28 / (view.pxPerBeat * 4)) : 1;
  const first = Math.floor(view.scroll);
  const last = Math.ceil(view.scroll + visibleBeats());
  for (let b = first; b <= last; b++) {
    const x = Math.round(beatToX(b)) + 0.5;
    if (b % 4 === 0) {
      const bar = b / 4;
      if (bar % barEvery === 0) {
        ctx.fillText(String(bar + 1), x + 3, 12);
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

  if (beat !== null) {
    const x = beatToX(beat);
    ctx.fillStyle = "#ffffff";
    ctx.beginPath();
    ctx.moveTo(x - 5, h - 10);
    ctx.lineTo(x + 5, h - 10);
    ctx.lineTo(x, h - 2);
    ctx.fill();
  }
}

function drawClip(ctx, clip, trackIndex, top, selected, audible) {
  const x0 = beatToX(clip.start);
  const x1 = beatToX(clip.start + clip.length);
  if (x1 < 0 || x0 > lanes.clientWidth) return;
  const color = trackColor(trackIndex);
  const y0 = top + 4;
  const height = TRACK_H - 8;
  const width = Math.max(4, x1 - x0 - 1);
  const data = clipRender(clip.id);
  const failed = Boolean(data?.error);

  ctx.save();
  ctx.globalAlpha = audible ? 1 : 0.35;
  ctx.beginPath();
  ctx.roundRect(x0 + 0.5, y0 + 0.5, width, height, 6);
  ctx.fillStyle = color;
  ctx.globalAlpha *= 0.16;
  ctx.fill();
  ctx.globalAlpha = audible ? 1 : 0.35;
  ctx.lineWidth = selected ? 2 : 1;
  ctx.strokeStyle = failed ? cssVar("--bad", "#ff5d6c") : selected ? "#ffffff" : color;
  ctx.stroke();
  ctx.clip();

  // label
  ctx.font = "11px ui-monospace, Menlo, monospace";
  ctx.fillStyle = failed ? cssVar("--bad", "#ff5d6c") : cssVar("--text", "#fff");
  const label = `${failed ? "⚠ " : ""}${clip.name || `y = ${clip.expression}`}`;
  ctx.fillText(label, x0 + 6, y0 + 13);

  // the clip's curve: each sample at its note's time, scaled to the clip's y range
  const samples = data?.samples ?? [];
  const [lo, hi] = data?.bounds ?? [0, 1];
  const span = hi - lo || 1;
  const plotTop = y0 + 18;
  const plotH = height - 24;
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  let pen = false;
  for (const s of samples) {
    if (s.y === null) {
      pen = false;
      continue;
    }
    const px = beatToX(s.start + s.duration / 2);
    const py = plotTop + (1 - clamp((s.y - lo) / span, 0, 1)) * plotH;
    if (pen) ctx.lineTo(px, py);
    else ctx.moveTo(px, py);
    pen = true;
  }
  ctx.stroke();
  if (view.pxPerBeat * clip.length / Math.max(samples.length, 1) > 5) {
    ctx.fillStyle = color;
    for (const s of samples) {
      if (s.y === null) continue;
      const px = beatToX(s.start + s.duration / 2);
      const py = plotTop + (1 - clamp((s.y - lo) / span, 0, 1)) * plotH;
      ctx.fillRect(px - 1.5, py - 1.5, 3, 3);
    }
  }

  // resize grip
  if (selected) {
    ctx.fillStyle = "#ffffff";
    ctx.globalAlpha = 0.5;
    ctx.fillRect(x0 + width - 4, y0 + height / 2 - 8, 2, 16);
  }
  ctx.restore();
}

/** The track's rendered level, drawn as a mirrored waveform behind its clips. */
function drawPeaks(ctx, peaks, top, color) {
  const perBeat = state.render?.peaks_per_beat ?? 8;
  if (!peaks?.length) return;
  const mid = top + TRACK_H / 2;
  const half = TRACK_H / 2 - 6;
  const first = Math.max(0, Math.floor(view.scroll * perBeat));
  const last = Math.min(peaks.length - 1, Math.ceil((view.scroll + visibleBeats()) * perBeat));
  const width = Math.max(1, view.pxPerBeat / perBeat);
  ctx.fillStyle = color;
  ctx.globalAlpha = 0.13;
  for (let i = first; i <= last; i++) {
    const amplitude = Math.min(1, peaks[i]) * half;
    if (amplitude < 0.5) continue;
    ctx.fillRect(beatToX(i / perBeat), mid - amplitude, width, amplitude * 2);
  }
  ctx.globalAlpha = 1;
}

// Automation curves are sampled by the server and cached per formula and song length.
const automationCache = new Map();

export function songLength() {
  return Math.max(16, ...(state.project?.tracks.flatMap((t) => t.clips.map((c) => c.start + c.length)) ?? []));
}

function automationCurve(formula, length) {
  const key = `${formula}|${length}`;
  if (automationCache.has(key)) return automationCache.get(key);
  automationCache.set(key, null);
  if (automationCache.size > 100) automationCache.delete(automationCache.keys().next().value);
  plot(formula, 0, length, 400)
    .then((data) => {
      automationCache.set(key, data);
      emit("view");
    })
    .catch(() => automationCache.set(key, { x: [], y: [] }));
  return null;
}

/** Gain automation (0 at the lane's bottom, 1 at its top) and pan automation (centre line ± half). */
function drawAutomation(ctx, track, top) {
  const length = songLength();
  const lanesFor = [
    ["gain", "#34d399", (v) => top + TRACK_H - 5 - clamp(v, 0, 1.5) / 1.5 * (TRACK_H - 10)],
    ["pan", "#60a5fa", (v) => top + TRACK_H / 2 - clamp(v, -1, 1) * (TRACK_H / 2 - 6)],
  ];
  for (const [key, color, toY] of lanesFor) {
    const formula = track.automation?.[key];
    if (!formula) continue;
    const data = automationCurve(formula, length);
    if (!data?.x?.length) continue;
    ctx.strokeStyle = color;
    ctx.globalAlpha = 0.75;
    ctx.lineWidth = 1.25;
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    let pen = false;
    for (let i = 0; i < data.x.length; i++) {
      if (data.y[i] === null) {
        pen = false;
        continue;
      }
      const px = beatToX(data.x[i]);
      const py = toY(data.y[i]);
      if (pen) ctx.lineTo(px, py);
      else ctx.moveTo(px, py);
      pen = true;
    }
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;
  }
}

export function drawLanes(beat) {
  const p = state.project;
  if (!p) return;
  const height = Math.max(p.tracks.length * TRACK_H, wrap.clientHeight);
  if (lanes.style.height !== `${height}px`) lanes.style.height = `${height}px`;
  const { ctx, w, h } = prepareCanvas(lanes);
  const renderTracks = new Map((state.render?.tracks ?? []).map((t) => [t.id, t]));
  const audible = new Map([...renderTracks].map(([id, t]) => [id, t.audible]));

  p.tracks.forEach((track, i) => {
    const top = i * TRACK_H;
    ctx.fillStyle = cssVar(i % 2 ? "--panel" : "--bg", "#000");
    if (track.id === state.selection.track) ctx.fillStyle = cssVar("--panel-2", "#1c1c1e");
    ctx.fillRect(0, top, w, TRACK_H);
    ctx.fillStyle = cssVar("--line", "#2b2b2e");
    ctx.fillRect(0, top + TRACK_H - 1, w, 1);
  });
  drawGrid(ctx, w, h);
  drawLoop(ctx, h);

  p.tracks.forEach((track, i) => {
    drawPeaks(ctx, renderTracks.get(track.id)?.peaks, i * TRACK_H, trackColor(i));
    for (const clip of track.clips) {
      drawClip(ctx, clip, i, i * TRACK_H, clip.id === state.selection.clip, audible.get(track.id) ?? true);
    }
    drawAutomation(ctx, track, i * TRACK_H);
  });

  if (!p.tracks.length) {
    ctx.fillStyle = cssVar("--muted", "#8f8f98");
    ctx.font = "13px sans-serif";
    ctx.fillText("Add a track to start. Double-click a lane to add a clip.", 16, 28);
  }

  if (beat !== null) {
    const x = Math.round(beatToX(beat)) + 0.5;
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();
  }
}

// ---------------------------------------------------------------- view

export function zoomAt(factor, anchorX = lanes.clientWidth / 2) {
  const anchor = xToBeat(anchorX);
  view.pxPerBeat = clamp(view.pxPerBeat * factor, MIN_PX_PER_BEAT, MAX_PX_PER_BEAT);
  view.scroll = Math.max(0, anchor - anchorX / view.pxPerBeat);
  emit("view");
}

export function zoomToFit() {
  const end = songLength();
  view.pxPerBeat = clamp((lanes.clientWidth - 24) / end, MIN_PX_PER_BEAT, MAX_PX_PER_BEAT);
  view.scroll = 0;
  emit("view");
}

/** Keep the playhead visible while playing. */
export function follow(beat) {
  const right = view.scroll + visibleBeats();
  if (beat > right - 1 || beat < view.scroll) {
    view.scroll = Math.max(0, beat - 1);
    emit("view");
  }
}

// ---------------------------------------------------------------- interaction

function hitTest(x, y) {
  const p = state.project;
  const index = Math.floor(y / TRACK_H);
  const track = p.tracks[index] ?? null;
  if (!track) return { track: null, index, clip: null, edge: false };
  for (let i = track.clips.length - 1; i >= 0; i--) {
    const clip = track.clips[i];
    const x0 = beatToX(clip.start);
    const x1 = beatToX(clip.start + clip.length);
    if (x >= x0 && x <= x1) return { track, index, clip, edge: x >= x1 - EDGE_PX };
  }
  return { track, index, clip: null, edge: false };
}

function onLanesDown(event) {
  if (event.button !== 0) return;
  const { x, y } = local(event, lanes);
  const hit = hitTest(x, y);
  if (!hit.track) {
    select(null, null);
    return;
  }
  select(hit.track.id, hit.clip?.id ?? null);
  if (!hit.clip) return;
  drag = {
    mode: hit.edge ? "resize" : "move",
    clipId: hit.clip.id,
    startX: event.clientX,
    origStart: hit.clip.start,
    origLength: hit.clip.length,
  };
  lanes.classList.add("dragging");
  event.preventDefault();
}

function onWindowMove(event) {
  if (drag) {
    const delta = (event.clientX - drag.startX) / view.pxPerBeat;
    const found = findClip(drag.clipId);
    if (!found) return;
    if (drag.mode === "resize") {
      const length = Math.max(view.snap, snapBeat(drag.origLength + delta));
      if (length !== found.clip.length) live(() => (found.clip.length = length));
      return;
    }
    const start = Math.max(0, snapBeat(drag.origStart + delta));
    const { y } = local(event, lanes);
    const tracks = state.project.tracks;
    const target = tracks[clamp(Math.floor(y / TRACK_H), 0, tracks.length - 1)];
    if (start === found.clip.start && target === found.track) return;
    live(() => {
      found.clip.start = start;
      if (target !== found.track) {
        found.track.clips.splice(found.track.clips.indexOf(found.clip), 1);
        target.clips.push(found.clip);
        state.selection.track = target.id;
      }
    });
    return;
  }
  if (rulerDrag) {
    const { x } = local(event, ruler);
    if (Math.abs(x - rulerDrag.x) < 4 && !rulerDrag.moved) return;
    rulerDrag.moved = true;
    const a = snapBeat(rulerDrag.beat);
    const b = snapBeat(Math.max(0, xToBeat(x)));
    const start = Math.min(a, b);
    const end = Math.max(Math.max(a, b), start + view.snap);
    live((p) => {
      p.loop_start = start;
      p.loop_end = end;
      p.loop_enabled = true;
    });
  }
}

function onWindowUp() {
  if (drag) {
    drag = null;
    lanes.classList.remove("dragging");
    settle();
  }
  if (rulerDrag) {
    if (!rulerDrag.moved) seekBeat(rulerDrag.beat);
    else settle();
    rulerDrag = null;
  }
}

function onLanesHover(event) {
  if (drag) return;
  const { x, y } = local(event, lanes);
  const hit = hitTest(x, y);
  lanes.style.cursor = hit.clip ? (hit.edge ? "ew-resize" : "grab") : "default";
}

function onLanesDouble(event) {
  const { x, y } = local(event, lanes);
  const hit = hitTest(x, y);
  if (hit.clip) {
    emit("focus-clip");
    return;
  }
  const start = Math.max(0, Math.floor(xToBeat(x) / view.snap) * view.snap);
  const clip = newClip(start);
  if (hit.track) {
    edit(() => hit.track.clips.push(clip));
    select(hit.track.id, clip.id);
  } else {
    const track = newTrack(state.project.tracks.length);
    track.clips.push(clip);
    edit((p) => p.tracks.push(track));
    select(track.id, clip.id);
  }
  emit("focus-clip");
}

function onWheel(event) {
  if (event.ctrlKey || event.metaKey) {
    event.preventDefault();
    zoomAt(Math.exp(-event.deltaY * 0.01), local(event, lanes).x);
    return;
  }
  const horizontal = event.shiftKey ? event.deltaY : event.deltaX;
  if (Math.abs(horizontal) > Math.abs(event.shiftKey ? 0 : event.deltaY)) {
    event.preventDefault();
    view.scroll = Math.max(0, view.scroll + horizontal / view.pxPerBeat);
    emit("view");
  }
}

export function initArrange(elements) {
  ({ ruler, lanes, wrap } = elements);
  lanes.addEventListener("mousedown", onLanesDown);
  lanes.addEventListener("mousemove", onLanesHover);
  lanes.addEventListener("dblclick", onLanesDouble);
  lanes.addEventListener("wheel", onWheel, { passive: false });
  ruler.addEventListener("wheel", onWheel, { passive: false });
  ruler.addEventListener("mousedown", (event) => {
    if (event.button !== 0) return;
    const { x } = local(event, ruler);
    rulerDrag = { x, beat: Math.max(0, xToBeat(x)), moved: false };
  });
  window.addEventListener("mousemove", onWindowMove);
  window.addEventListener("mouseup", onWindowUp);
}
