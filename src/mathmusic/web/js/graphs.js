// Graphs of formulas: a generic function plot used for every formula field,
// and the clip graph that shows a curve against the scale's pitch lattice.

import { plot as fetchPlot } from "./api.js";
import { clamp, cssVar, formatTick, noteName, prepareCanvas, ticks } from "./util.js";

const PAD = { left: 38, right: 10, top: 10, bottom: 20 };

function range(values, fallback) {
  const finite = values.filter((v) => v !== null && Number.isFinite(v));
  if (!finite.length) return fallback;
  let lo = Math.min(...finite);
  let hi = Math.max(...finite);
  if (hi - lo < 1e-9) {
    lo -= 1;
    hi += 1;
  }
  const pad = (hi - lo) * 0.08;
  return [lo - pad, hi + pad];
}

function axes(ctx, w, h, xr, yr, { xLabel = "", rightLabels = null } = {}) {
  const line = cssVar("--line", "#2b2b2e");
  const muted = cssVar("--muted", "#8f8f98");
  const plotW = w - PAD.left - PAD.right;
  const plotH = h - PAD.top - PAD.bottom;
  const X = (x) => PAD.left + ((x - xr[0]) / (xr[1] - xr[0])) * plotW;
  const Y = (y) => PAD.top + (1 - (y - yr[0]) / (yr[1] - yr[0])) * plotH;
  ctx.font = "10px ui-monospace, Menlo, monospace";
  ctx.lineWidth = 1;

  const xt = ticks(xr[0], xr[1], Math.max(2, Math.floor(plotW / 70)));
  const yt = ticks(yr[0], yr[1], Math.max(2, Math.floor(plotH / 34)));
  ctx.strokeStyle = line;
  ctx.beginPath();
  for (const v of xt.values) {
    const x = Math.round(X(v)) + 0.5;
    ctx.moveTo(x, PAD.top);
    ctx.lineTo(x, PAD.top + plotH);
  }
  if (!rightLabels) {
    for (const v of yt.values) {
      const y = Math.round(Y(v)) + 0.5;
      ctx.moveTo(PAD.left, y);
      ctx.lineTo(PAD.left + plotW, y);
    }
  }
  ctx.stroke();

  ctx.strokeStyle = muted;
  ctx.globalAlpha = 0.6;
  ctx.beginPath();
  if (yr[0] <= 0 && yr[1] >= 0) {
    ctx.moveTo(PAD.left, Math.round(Y(0)) + 0.5);
    ctx.lineTo(PAD.left + plotW, Math.round(Y(0)) + 0.5);
  }
  if (xr[0] <= 0 && xr[1] >= 0) {
    ctx.moveTo(Math.round(X(0)) + 0.5, PAD.top);
    ctx.lineTo(Math.round(X(0)) + 0.5, PAD.top + plotH);
  }
  ctx.stroke();
  ctx.globalAlpha = 1;

  ctx.fillStyle = muted;
  for (const v of xt.values) ctx.fillText(formatTick(v, xt.step), X(v) + 2, h - 6);
  if (!rightLabels) {
    for (const v of yt.values) {
      const text = formatTick(v, yt.step);
      ctx.fillText(text, PAD.left - 4 - ctx.measureText(text).width, Y(v) + 3);
    }
  }
  if (xLabel) {
    const width = ctx.measureText(xLabel).width;
    ctx.fillText(xLabel, PAD.left + plotW - width, PAD.top + plotH - 4);
  }
  return { X, Y, plotW, plotH };
}

function line(ctx, xs, ys, X, Y, color, width = 2) {
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.beginPath();
  let pen = false;
  for (let i = 0; i < xs.length; i++) {
    if (ys[i] === null || !Number.isFinite(ys[i])) {
      pen = false;
      continue;
    }
    const px = X(xs[i]);
    const py = Y(ys[i]);
    if (pen) ctx.lineTo(px, py);
    else ctx.moveTo(px, py);
    pen = true;
  }
  ctx.stroke();
}

function message(canvas, text, color) {
  const { ctx, w, h } = prepareCanvas(canvas);
  ctx.fillStyle = color || cssVar("--muted", "#8f8f98");
  ctx.font = "12px ui-monospace, Menlo, monospace";
  ctx.fillText(text, 12, h / 2);
  return { ctx, w, h };
}

/**
 * A canvas that shows y = f(x) for a formula, fetched from the server.
 * show() is safe to call often: stale responses are ignored.
 */
export class FormulaPlot {
  constructor(canvas, { color = "#25f4ee", xLabel = "x", yRange = null, points = 240 } = {}) {
    this.canvas = canvas;
    this.color = color;
    this.xLabel = xLabel;
    this.yRange = yRange;
    this.points = points;
    this.seq = 0;
    this.last = null;
  }

  async show(formula, start, end, { marker = null, fallback = null } = {}) {
    const text = (formula || "").trim() || fallback;
    const key = `${text}|${start}|${end}|${marker}`;
    if (key === this.last) return;
    this.last = key;
    const mine = ++this.seq;
    if (!text) {
      message(this.canvas, "no formula");
      return;
    }
    try {
      const data = await fetchPlot(text, start, end, this.points);
      if (mine !== this.seq) return;
      this.draw(data, marker);
    } catch (error) {
      if (mine !== this.seq) return;
      message(this.canvas, error.message, cssVar("--bad", "#ff5d6c"));
    }
  }

  draw(data, marker) {
    const { ctx, w, h } = prepareCanvas(this.canvas);
    const xr = [data.x[0], data.x[data.x.length - 1]];
    const yr = this.yRange ?? range(data.y, [-1, 1]);
    const { X, Y } = axes(ctx, w, h, xr, yr, { xLabel: this.xLabel });
    line(ctx, data.x, data.y, X, Y, this.color);
    if (marker !== null && marker >= xr[0] && marker <= xr[1]) {
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(Math.round(X(marker)) + 0.5, PAD.top);
      ctx.lineTo(Math.round(X(marker)) + 0.5, h - PAD.bottom);
      ctx.stroke();
    }
    if (data.y.some((v) => v === null)) {
      ctx.fillStyle = cssVar("--bad", "#ff5d6c");
      ctx.fillText("undefined in places", PAD.left + 4, PAD.top + 12);
    }
  }
}

/**
 * The clip graph: the curve y = f(x) with the pitch lattice behind it.
 * Each horizontal line is a note of the scale; each sample snaps to the nearest.
 */
export function drawClipGraph(canvas, { samples, bounds, pitches, invert, color, playBeat = null, hover = null }) {
  const { ctx, w, h } = prepareCanvas(canvas);
  if (!samples?.length) {
    message(canvas, "no samples to draw");
    return null;
  }
  const xs = samples.map((s) => s.x);
  const ys = samples.map((s) => s.y);
  const [lo, hi] = bounds;
  const span = hi - lo || 1;
  const yr = range([...ys, lo, hi], [-1, 1]);
  const xr = [xs[0], xs[xs.length - 1] === xs[0] ? xs[0] + 1 : xs[xs.length - 1]];
  const geometry = axes(ctx, w - 34, h, xr, yr, { xLabel: "x", rightLabels: true });
  const { X, Y, plotW } = geometry;
  const right = PAD.left + plotW;

  // pitch lattice: value v_k = lo + k/(n-1) * (hi - lo) maps to pitch k (reversed when inverted)
  const n = pitches.length;
  ctx.font = "10px ui-monospace, Menlo, monospace";
  for (let k = 0; k < n; k++) {
    const value = lo + (n === 1 ? 0.5 : k / (n - 1)) * span;
    const y = Math.round(Y(value)) + 0.5;
    if (y < PAD.top - 1 || y > h - PAD.bottom + 1) continue;
    const pitch = pitches[invert ? n - 1 - k : k];
    const isRoot = k === 0 || (pitch - pitches[0]) % 12 === 0;
    ctx.strokeStyle = cssVar("--line", "#2b2b2e");
    ctx.globalAlpha = isRoot ? 1 : 0.55;
    ctx.beginPath();
    ctx.moveTo(PAD.left, y);
    ctx.lineTo(right, y);
    ctx.stroke();
    ctx.globalAlpha = 1;
    if (n <= 30 || isRoot) {
      ctx.fillStyle = isRoot ? cssVar("--text", "#fff") : cssVar("--muted", "#8f8f98");
      ctx.fillText(noteName(pitch), right + 4, y + 3);
    }
  }

  // the curve, then each sample's quantised note as a tick on the lattice
  line(ctx, xs, ys, X, Y, color, 2);
  for (const s of samples) {
    if (s.y === null || s.pitch === null) continue;
    const k = pitches.indexOf(s.pitch);
    const index = invert ? n - 1 - k : k;
    const latticeY = Y(lo + (n === 1 ? 0.5 : index / (n - 1)) * span);
    const px = X(s.x);
    ctx.strokeStyle = color;
    ctx.globalAlpha = 0.45;
    ctx.beginPath();
    ctx.moveTo(px, Y(clamp(s.y, yr[0], yr[1])));
    ctx.lineTo(px, latticeY);
    ctx.stroke();
    ctx.globalAlpha = 1;
    ctx.fillStyle = color;
    ctx.fillRect(px - 3, latticeY - 1.5, 6, 3);
  }

  if (playBeat !== null) {
    const playing = samples.find((s) => playBeat >= s.start && playBeat < s.start + s.duration);
    if (playing && playing.y !== null) {
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(X(playing.x), Y(playing.y), 6, 0, Math.PI * 2);
      ctx.stroke();
    }
  }
  if (hover) {
    ctx.strokeStyle = cssVar("--text", "#fff");
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(X(hover.x), Y(hover.y), 9, 0, Math.PI * 2);
    ctx.stroke();
  }
  return { X, Y, xr, yr };
}

/** MIDI pitches for a scale across octaves, plus the top tonic (matches scales.pitch_table). */
export function pitchTable(degrees, rootMidi, octaves) {
  const pitches = [];
  for (let o = 0; o < octaves; o++) for (const d of degrees) pitches.push(rootMidi + 12 * o + d);
  pitches.push(rootMidi + 12 * octaves);
  return pitches;
}
