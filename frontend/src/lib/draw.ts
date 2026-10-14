// Canvas drawing for every graph in the DAW: formula plots, the clip graph
// over the pitch lattice, sample waveforms and level meters.

import type { PlotData, Sample } from "./types";
import { type Canvas2D, clamp, color, formatTick, noteName, prepareCanvas, ticks } from "./util";

const PAD = { left: 38, right: 10, top: 10, bottom: 20 };

type Range = [number, number];

export interface Geometry {
  X: (x: number) => number;
  Y: (y: number) => number;
  xr: Range;
  yr: Range;
  plotW: number;
}

function range(values: (number | null)[], fallback: Range): Range {
  const finite = values.filter((v): v is number => v !== null && Number.isFinite(v));
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

function axes({ ctx, w, h }: Canvas2D, xr: Range, yr: Range, xLabel = "", hideY = false): Geometry {
  const line = color("line", "#2b2b2e");
  const muted = color("muted", "#8f8f98");
  const plotW = w - PAD.left - PAD.right;
  const plotH = h - PAD.top - PAD.bottom;
  const X = (x: number) => PAD.left + ((x - xr[0]) / (xr[1] - xr[0])) * plotW;
  const Y = (y: number) => PAD.top + (1 - (y - yr[0]) / (yr[1] - yr[0])) * plotH;
  ctx.font = "10px 'JetBrains Mono', ui-monospace, monospace";
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
  if (!hideY) {
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
  if (!hideY) {
    for (const v of yt.values) {
      const text = formatTick(v, yt.step);
      ctx.fillText(text, PAD.left - 4 - ctx.measureText(text).width, Y(v) + 3);
    }
  }
  if (xLabel) {
    ctx.fillText(xLabel, PAD.left + plotW - ctx.measureText(xLabel).width, PAD.top + plotH - 4);
  }
  return { X, Y, xr, yr, plotW };
}

function polyline(ctx: CanvasRenderingContext2D, xs: number[], ys: (number | null)[], g: Geometry, stroke: string) {
  ctx.strokeStyle = stroke;
  ctx.lineWidth = 2;
  ctx.beginPath();
  let pen = false;
  for (let i = 0; i < xs.length; i++) {
    const y = ys[i];
    if (y === null || !Number.isFinite(y)) {
      pen = false;
      continue;
    }
    if (pen) ctx.lineTo(g.X(xs[i]), g.Y(y));
    else ctx.moveTo(g.X(xs[i]), g.Y(y));
    pen = true;
  }
  ctx.stroke();
}

export function drawMessage(canvas: HTMLCanvasElement, text: string, tone: "muted" | "bad" = "muted"): void {
  const { ctx, h } = prepareCanvas(canvas);
  ctx.fillStyle = color(tone, "#8f8f98");
  ctx.font = "12px 'JetBrains Mono', ui-monospace, monospace";
  ctx.fillText(text, 12, h / 2);
}

export interface FormulaPlotOptions {
  stroke: string;
  xLabel: string;
  yRange: Range | null;
  marker: number | null;
}

export function drawFormula(canvas: HTMLCanvasElement, data: PlotData, opts: FormulaPlotOptions): void {
  const surface = prepareCanvas(canvas);
  const xr: Range = [data.x[0], data.x[data.x.length - 1]];
  const yr = opts.yRange ?? range(data.y, [-1, 1]);
  const g = axes(surface, xr, yr, opts.xLabel);
  polyline(surface.ctx, data.x, data.y, g, opts.stroke);
  const { ctx, h } = surface;
  if (opts.marker !== null && opts.marker >= xr[0] && opts.marker <= xr[1]) {
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(Math.round(g.X(opts.marker)) + 0.5, PAD.top);
    ctx.lineTo(Math.round(g.X(opts.marker)) + 0.5, h - PAD.bottom);
    ctx.stroke();
  }
  if (data.y.some((v) => v === null)) {
    ctx.fillStyle = color("bad", "#ff5d6c");
    ctx.fillText("undefined in places", PAD.left + 4, PAD.top + 12);
  }
}

export interface ClipGraphOptions {
  samples: Sample[];
  bounds: Range;
  pitches: number[];
  invert: boolean;
  stroke: string;
  playBeat: number | null;
  hover: Sample | null;
}

/**
 * The clip graph: the curve y = f(x) with the pitch lattice behind it.
 * Each horizontal line is a note of the scale; each sample snaps to the nearest.
 */
export function drawClipGraph(canvas: HTMLCanvasElement, o: ClipGraphOptions): Geometry | null {
  if (!o.samples.length) {
    drawMessage(canvas, "no samples to draw");
    return null;
  }
  const surface = prepareCanvas(canvas);
  const { ctx, h } = surface;
  const xs = o.samples.map((s) => s.x);
  const ys = o.samples.map((s) => s.y);
  const [lo, hi] = o.bounds;
  const span = hi - lo || 1;
  const yr = range([...ys, lo, hi], [-1, 1]);
  const last = xs[xs.length - 1];
  const xr: Range = [xs[0], last === xs[0] ? xs[0] + 1 : last];
  const g = axes({ ...surface, w: surface.w - 34 }, xr, yr, "x", true);
  const right = PAD.left + g.plotW;
  const n = o.pitches.length;
  const latticeValue = (index: number) => lo + (n === 1 ? 0.5 : index / (n - 1)) * span;

  ctx.font = "10px 'JetBrains Mono', ui-monospace, monospace";
  for (let k = 0; k < n; k++) {
    const y = Math.round(g.Y(latticeValue(k))) + 0.5;
    if (y < PAD.top - 1 || y > h - PAD.bottom + 1) continue;
    const pitch = o.pitches[o.invert ? n - 1 - k : k];
    const isRoot = (pitch - o.pitches[0]) % 12 === 0;
    ctx.strokeStyle = color("line", "#2b2b2e");
    ctx.globalAlpha = isRoot ? 1 : 0.55;
    ctx.beginPath();
    ctx.moveTo(PAD.left, y);
    ctx.lineTo(right, y);
    ctx.stroke();
    ctx.globalAlpha = 1;
    if (n <= 30 || isRoot) {
      ctx.fillStyle = isRoot ? color("ink", "#fff") : color("muted", "#8f8f98");
      ctx.fillText(noteName(pitch), right + 4, y + 3);
    }
  }

  polyline(ctx, xs, ys, g, o.stroke);
  for (const s of o.samples) {
    if (s.y === null || s.pitch === null) continue;
    const k = o.pitches.indexOf(s.pitch);
    const latticeY = g.Y(latticeValue(o.invert ? n - 1 - k : k));
    const px = g.X(s.x);
    ctx.strokeStyle = o.stroke;
    ctx.globalAlpha = 0.45;
    ctx.beginPath();
    ctx.moveTo(px, g.Y(clamp(s.y, yr[0], yr[1])));
    ctx.lineTo(px, latticeY);
    ctx.stroke();
    ctx.globalAlpha = 1;
    ctx.fillStyle = o.stroke;
    ctx.fillRect(px - 3, latticeY - 1.5, 6, 3);
  }

  const ring = (s: Sample, radius: number, stroke: string, width: number) => {
    if (s.y === null) return;
    ctx.strokeStyle = stroke;
    ctx.lineWidth = width;
    ctx.beginPath();
    ctx.arc(g.X(s.x), g.Y(s.y), radius, 0, Math.PI * 2);
    ctx.stroke();
  };
  if (o.playBeat !== null) {
    const beat = o.playBeat;
    const playing = o.samples.find((s) => beat >= s.start && beat < s.start + s.duration);
    if (playing) ring(playing, 6, "#ffffff", 2);
  }
  if (o.hover) ring(o.hover, 9, color("ink", "#fff"), 1);
  return g;
}

/** A sample's level over time as a mirrored waveform. */
export function drawPeaks(
  canvas: HTMLCanvasElement,
  peaks: number[],
  stroke: string,
  playFraction: number | null,
): void {
  const { ctx, w, h } = prepareCanvas(canvas);
  if (!peaks.length) {
    drawMessage(canvas, "no audio");
    return;
  }
  const mid = h / 2;
  ctx.fillStyle = stroke;
  ctx.globalAlpha = 0.75;
  const width = w / peaks.length;
  peaks.forEach((peak, i) => {
    const amplitude = Math.max(0.5, Math.min(1, peak) * (h / 2 - 6));
    ctx.fillRect(i * width, mid - amplitude, Math.max(1, width - 0.5), amplitude * 2);
  });
  ctx.globalAlpha = 1;
  if (playFraction !== null && playFraction >= 0 && playFraction <= 1) {
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(Math.round(playFraction * w), 0, 1.5, h);
  }
}

const METER_FLOOR_DB = -48;

export function drawMeter(canvas: HTMLCanvasElement, level: number): void {
  const { ctx, w, h } = prepareCanvas(canvas);
  ctx.fillStyle = color("panel-3", "#222226");
  ctx.fillRect(0, 0, w, h);
  const db = level > 0 ? 20 * Math.log10(level) : -Infinity;
  const fraction = clamp((db - METER_FLOOR_DB) / -METER_FLOOR_DB, 0, 1);
  const gradient = ctx.createLinearGradient(0, h, 0, 0);
  gradient.addColorStop(0, color("neon-green", "#34d399"));
  gradient.addColorStop(0.75, color("neon-yellow", "#facc15"));
  gradient.addColorStop(1, color("accent", "#fe2c55"));
  ctx.fillStyle = gradient;
  ctx.fillRect(0, h * (1 - fraction), w, h * fraction);
  ctx.fillStyle = "rgb(0 0 0 / 0.55)";
  for (let mark = -12; mark > METER_FLOOR_DB; mark -= 12)
    ctx.fillRect(0, Math.round(h * (mark / METER_FLOOR_DB)), w, 1);
}

/** Peak level around a beat, from the rendered level data. */
export function levelAt(peaks: number[] | undefined, beat: number | null, perBeat: number): number {
  if (!peaks?.length || beat === null) return 0;
  const i = Math.floor(beat * perBeat);
  let level = 0;
  for (let k = i - 1; k <= i + 1; k++) if (k >= 0 && k < peaks.length) level = Math.max(level, peaks[k]);
  return level;
}
