// Shared helpers: formatting, axis maths and canvas setup.

export const PALETTE = ["#25f4ee", "#a855f7", "#facc15", "#fe2c55", "#34d399", "#f472b6", "#60a5fa", "#fb923c"];
export const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

export const trackColor = (index: number): string =>
  PALETTE[((index % PALETTE.length) + PALETTE.length) % PALETTE.length];

export const clamp = (value: number, low: number, high: number): number => Math.min(Math.max(value, low), high);

export function uid(prefix: string): string {
  return `${prefix}${Math.random().toString(36).slice(2, 10)}`;
}

export function debounce<A extends unknown[]>(fn: (...args: A) => void, wait: number): (...args: A) => void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  return (...args: A) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

export function noteName(midi: number): string {
  return `${NOTE_NAMES[((midi % 12) + 12) % 12]}${Math.floor(midi / 12) - 1}`;
}

export function parseNote(name: string): number | null {
  const match = /^([A-Ga-g])([#b]?)(-?\d+)$/.exec(String(name).trim());
  if (!match) return null;
  const offsets: Record<string, number> = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
  const accidental: Record<string, number> = { "": 0, "#": 1, b: -1 };
  return 12 * (Number(match[3]) + 1) + offsets[match[1].toUpperCase()] + accidental[match[2]];
}

/** MIDI pitches for a scale across octaves, plus the top tonic (matches scales.pitch_table). */
export function pitchTable(degrees: number[], rootMidi: number, octaves: number): number[] {
  const pitches: number[] = [];
  for (let o = 0; o < octaves; o++) for (const d of degrees) pitches.push(rootMidi + 12 * o + d);
  pitches.push(rootMidi + 12 * octaves);
  return pitches;
}

export function fmtTime(seconds: number): string {
  const s = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
  const minutes = Math.floor(s / 60);
  return `${minutes}:${(s - minutes * 60).toFixed(1).padStart(4, "0")}`;
}

/** Bars.beats.hundredths, 1-based like most DAWs. */
export function fmtPosition(beat: number, beatsPerBar: number): string {
  const b = Math.max(0, beat);
  const bar = Math.floor(b / beatsPerBar) + 1;
  const inBar = Math.floor(b % beatsPerBar) + 1;
  const sub = Math.floor((b % 1) * 100);
  return `${bar}.${inBar}.${String(sub).padStart(2, "0")}`;
}

/** Numbers shown with at most 6 decimals (12.566370614359172 -> 12.566371). */
export function fmtNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "";
  return String(Number.isInteger(value) ? value : Number(value.toFixed(6)));
}

export function fmtDb(db: number): string {
  return db <= -60 ? "-∞ dB" : `${db > 0 ? "+" : ""}${db.toFixed(1)} dB`;
}

export function fmtPan(pan: number): string {
  if (Math.abs(pan) < 0.01) return "C";
  return `${pan < 0 ? "L" : "R"}${Math.round(Math.abs(pan) * 100)}`;
}

export function niceStep(range: number, count: number): number {
  const raw = range / Math.max(count, 1);
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const normalised = raw / magnitude;
  const factor = normalised < 1.5 ? 1 : normalised < 3 ? 2 : normalised < 7 ? 5 : 10;
  return factor * magnitude;
}

export function ticks(min: number, max: number, count: number): { values: number[]; step: number } {
  const step = niceStep(max - min, count);
  const values: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) {
    values.push(Math.abs(v) < step * 1e-9 ? 0 : v);
  }
  return { values, step };
}

export const formatTick = (value: number, step: number): string =>
  value.toFixed(Math.max(0, Math.ceil(-Math.log10(step))));

/** Theme colours for canvas drawing, read from the Tailwind tokens. */
export function color(name: string, fallback = "#888"): string {
  if (typeof document === "undefined") return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(`--color-${name}`).trim() || fallback;
}

export interface Canvas2D {
  ctx: CanvasRenderingContext2D;
  w: number;
  h: number;
}

/** Size a canvas to its CSS box at device resolution and return a cleared 2D context. */
export function prepareCanvas(canvas: HTMLCanvasElement): Canvas2D {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
  }
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("canvas 2D is not available");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  return { ctx, w, h };
}

export function isTyping(event: Event): boolean {
  const target = event.target;
  return target instanceof HTMLElement && Boolean(target.closest("input, textarea, select, [contenteditable]"));
}

export function download(url: string, filename: string): void {
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
}

export function safeFilename(name: string): string {
  return name.replace(/[^A-Za-z0-9 _-]/g, "").trim() || "mathmusic";
}
