// Small shared helpers: DOM, formatting, canvas and axis maths.

export const PALETTE = ["#25f4ee", "#a855f7", "#facc15", "#fe2c55", "#34d399", "#f472b6", "#60a5fa", "#fb923c"];
export const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

export const $ = (selector, root = document) => root.querySelector(selector);

/** Create an element: el("button", { class: "ghost", onclick }, "Text", child) */
export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key in node && typeof value !== "string") node[key] = value;
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : String(child));
  }
  return node;
}

export const clamp = (value, low, high) => Math.min(Math.max(value, low), high);

export function uid(prefix) {
  return `${prefix}${Math.random().toString(36).slice(2, 10)}`;
}

export function debounce(fn, wait) {
  let timer = 0;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

export function noteName(midi) {
  return `${NOTE_NAMES[((midi % 12) + 12) % 12]}${Math.floor(midi / 12) - 1}`;
}

export function parseNote(name) {
  const match = /^([A-Ga-g])([#b]?)(-?\d+)$/.exec(String(name).trim());
  if (!match) return null;
  const offsets = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
  const accidental = { "": 0, "#": 1, b: -1 }[match[2]];
  return 12 * (Number(match[3]) + 1) + offsets[match[1].toUpperCase()] + accidental;
}

export function fmtTime(seconds) {
  const s = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
  const minutes = Math.floor(s / 60);
  return `${minutes}:${(s - minutes * 60).toFixed(1).padStart(4, "0")}`;
}

/** Bars.beats.hundredths in 4/4, 1-based like most DAWs. */
export function fmtPosition(beat) {
  const b = Math.max(0, beat);
  const bar = Math.floor(b / 4) + 1;
  const inBar = Math.floor(b % 4) + 1;
  const sub = Math.floor((b % 1) * 100);
  return `${bar}.${inBar}.${String(sub).padStart(2, "0")}`;
}

export function niceStep(range, count) {
  const raw = range / Math.max(count, 1);
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const normalised = raw / magnitude;
  const factor = normalised < 1.5 ? 1 : normalised < 3 ? 2 : normalised < 7 ? 5 : 10;
  return factor * magnitude;
}

export function ticks(min, max, count) {
  const step = niceStep(max - min, count);
  const values = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) {
    values.push(Math.abs(v) < step * 1e-9 ? 0 : v);
  }
  return { values, step };
}

export const formatTick = (value, step) => value.toFixed(Math.max(0, Math.ceil(-Math.log10(step))));

export function cssVar(name, fallback) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

/** Size a canvas to its CSS box at device resolution and return a cleared 2D context. */
export function prepareCanvas(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  return { ctx, w, h };
}

/** Set an input's value from the model unless the user is typing in it. */
export function setValue(input, value) {
  if (document.activeElement === input) return;
  // numbers are shown with at most 6 decimals (12.566370614359172 -> 12.566371)
  const shown = typeof value === "number" && !Number.isInteger(value) ? Number(value.toFixed(6)) : value;
  const text = shown === null || shown === undefined ? "" : String(shown);
  if (input.type === "checkbox") input.checked = Boolean(value);
  else if (input.value !== text) input.value = text;
}

export function isTyping(event) {
  const target = event.target;
  return target instanceof HTMLElement && Boolean(target.closest("input, textarea, select, [contenteditable]"));
}

export function download(url, filename) {
  const link = el("a", { href: url, download: filename });
  document.body.append(link);
  link.click();
  link.remove();
}
