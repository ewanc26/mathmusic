// mathmusic UI: expressions in, graph + piano roll + playback out.
// All synthesis happens on the server (/api/render) so playback matches the CLI exactly.

// neon orbit colours: cyan, purple, yellow, coral, green, pink
const PALETTE = ["#25f4ee", "#a855f7", "#facc15", "#fe2c55", "#34d399", "#f472b6"];
const SCALE_NAMES = ["pentatonic", "major", "minor", "dorian", "minor_pentatonic", "whole_tone", "chromatic"];
// filled from /api/instruments at boot: { waveforms: [{name, formula}], instruments: [{name, description, wave, envelope}] }
let catalogue = { waveforms: [], instruments: [] };
const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const STORAGE_KEY = "mathmusic.v1";

const PRESETS = [
  {
    name: "Three curves",
    exprs: ["sin(x)", "x^2/(2*pi*pi) - 0.5", "2*sinc(x-4)"],
    opts: { start: 0, end: 12.566, samples: 96, scale: "pentatonic", root: "C4", octaves: 2, bpm: 110, step: 0.5, rhythm: "uniform" },
  },
  {
    name: "Damped",
    exprs: ["sin(3*x)*exp(-x/6)"],
    opts: { start: 0, end: 20, samples: 160, scale: "minor", root: "A3", octaves: 2, bpm: 96, step: 0.25, rhythm: "slope" },
  },
  {
    name: "Gaussian",
    exprs: ["4*exp(-(x-6)^2/4)", "sin(x)"],
    opts: { start: 0, end: 12, samples: 120, scale: "dorian", root: "D4", octaves: 2, bpm: 100, step: 0.5, rhythm: "uniform" },
  },
  {
    name: "Beating",
    exprs: ["sin(2*x)+sin(3*x)", "cos(x/2)"],
    opts: { start: 0, end: 25, samples: 200, scale: "minor_pentatonic", root: "C3", octaves: 3, bpm: 90, step: 0.25, rhythm: "slope" },
  },
];

const $ = (selector) => document.querySelector(selector);
const audio = $("#audio");
const graphCanvas = $("#graph");
const rollCanvas = $("#roll");

let nextId = 1;
// waveform: null (auto), a waveform or instrument name, or a formula in x when custom is true
const newExpr = (src = "", waveform = null) => ({ id: nextId++, src, waveform, custom: false, enabled: true, invert: false });

let state = loadState() ?? { exprs: PRESETS[0].exprs.map((s) => newExpr(s)), opts: { pitch_mode: "shared", ...PRESETS[0].opts } };
let render = null; // last successful render from the server
let serverStatus = { ffmpeg: false, plyrfm: false, plyr_token: false };
let renderSeq = 0;
let renderTimer = 0;
let view = null; // graph viewport in data units
let autoFit = true;
let hover = null; // { voice, sample, px, py }
let drag = null;
let dirty = true;
let rollGeometry = null;

// ---------- persistence (per-viewer convenience only) ----------

function loadState() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (!saved || !Array.isArray(saved.exprs) || !saved.opts) return null;
    return {
      exprs: saved.exprs.map((e) => ({ ...newExpr(String(e.src ?? ""), e.waveform ?? null), custom: e.custom === true, enabled: e.enabled !== false, invert: e.invert === true })),
      opts: { pitch_mode: "shared", ...saved.opts },
    };
  } catch {
    return null;
  }
}

function saveState() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ exprs: state.exprs, opts: state.opts }));
  } catch {
    /* storage can be unavailable; the app works without it */
  }
}

// ---------- sidebar ----------

function renderPresets() {
  const nav = $("#presets");
  nav.replaceChildren(
    ...PRESETS.map((preset) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = preset.name;
      button.addEventListener("click", () => applyPreset(preset));
      return button;
    }),
  );
}

function applyPreset(preset) {
  state.exprs = preset.exprs.map((s) => newExpr(s));
  state.opts = { pitch_mode: "shared", ...preset.opts };
  autoFit = true;
  syncOptionInputs();
  renderExprs();
  scheduleRender(0);
}

function renderExprs() {
  const list = $("#exprs");
  list.replaceChildren(...state.exprs.map((expr, index) => exprRow(expr, index)));
  paintExprErrors(lastErrors);
}

let lastErrors = [];

function exprRow(expr, index) {
  const li = document.createElement("li");
  li.className = "expr";
  li.dataset.id = expr.id;

  const row = document.createElement("div");
  row.className = "expr-row";

  const swatch = document.createElement("span");
  swatch.className = "swatch";
  swatch.style.background = PALETTE[index % PALETTE.length];

  const input = document.createElement("input");
  input.type = "text";
  input.value = expr.src;
  input.placeholder = "e.g. sin(x)";
  input.spellcheck = false;
  input.autocomplete = "off";
  input.setAttribute("aria-label", `Expression ${index + 1}`);
  input.addEventListener("input", () => {
    expr.src = input.value;
    scheduleRender();
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") scheduleRender(0);
  });

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "icon";
  remove.title = "Remove expression";
  remove.textContent = "×";
  remove.addEventListener("click", () => {
    state.exprs = state.exprs.filter((e) => e.id !== expr.id);
    renderExprs();
    scheduleRender(0);
  });

  row.append(swatch, input, remove);

  const meta = document.createElement("div");
  meta.className = "expr-meta";

  const enabled = document.createElement("label");
  const check = document.createElement("input");
  check.type = "checkbox";
  check.checked = expr.enabled;
  check.addEventListener("change", () => {
    expr.enabled = check.checked;
    li.classList.toggle("off", !expr.enabled);
    scheduleRender(0);
  });
  enabled.append(check, " on");

  const invertLabel = document.createElement("label");
  invertLabel.title = "Flip the direction: high values sound low";
  const invertCheck = document.createElement("input");
  invertCheck.type = "checkbox";
  invertCheck.checked = expr.invert;
  invertCheck.addEventListener("change", () => {
    expr.invert = invertCheck.checked;
    scheduleRender(0);
  });
  invertLabel.append(invertCheck, " invert");

  const wave = document.createElement("select");
  wave.setAttribute("aria-label", `Sound for expression ${index + 1}`);
  wave.append(new Option("sound: auto", "auto"));
  const basics = document.createElement("optgroup");
  basics.label = "Waveforms";
  for (const w of catalogue.waveforms) basics.append(new Option(w.name, w.name));
  const instruments = document.createElement("optgroup");
  instruments.label = "Instruments";
  for (const inst of catalogue.instruments) {
    const option = new Option(inst.name, inst.name);
    option.title = inst.description;
    instruments.append(option);
  }
  wave.append(basics, instruments, new Option("custom formula…", "__custom__"));
  wave.value = expr.custom ? "__custom__" : (expr.waveform ?? "auto");

  // one period of the waveform, in x (x = phase in cycles)
  const formula = document.createElement("input");
  formula.type = "text";
  formula.className = "wave-formula";
  formula.placeholder = "one cycle in x, e.g. sin(2*pi*x) + 0.3*sin(6*pi*x)";
  formula.spellcheck = false;
  formula.autocomplete = "off";
  formula.setAttribute("aria-label", `Waveform formula for expression ${index + 1}`);
  formula.value = expr.custom ? expr.waveform ?? "" : "";
  formula.hidden = !expr.custom;
  formula.addEventListener("input", () => {
    if (!expr.custom) return; // a hidden field must not overwrite a named sound
    expr.waveform = formula.value;
    scheduleRender();
  });

  wave.addEventListener("change", () => {
    if (wave.value === "__custom__") {
      expr.custom = true;
      expr.waveform = formula.value || "sin(2*pi*x)";
      formula.value = expr.waveform;
      formula.hidden = false;
      formula.focus();
    } else {
      expr.custom = false;
      expr.waveform = wave.value === "auto" ? null : wave.value;
      formula.hidden = true;
    }
    scheduleRender(0);
  });

  const spacer = document.createElement("span");
  spacer.className = "spacer";
  meta.append(enabled, invertLabel, spacer, wave);

  const error = document.createElement("div");
  error.className = "expr-error";

  li.append(row, meta, formula, error);
  li.classList.toggle("off", !expr.enabled);
  return li;
}

function paintExprErrors(errors) {
  lastErrors = errors;
  const byIndex = new Map(errors.map((e) => [e.index, e.error]));
  document.querySelectorAll("#exprs > li").forEach((li, index) => {
    const message = byIndex.get(index) ?? "";
    li.classList.toggle("bad", Boolean(message));
    li.querySelector(".expr-error").textContent = message;
  });
}

// Sound and domain controls bind to state.opts through data-opt attributes.
function syncOptionInputs() {
  $("#scale-select").replaceChildren(
    ...SCALE_NAMES.map((name) => new Option(name.replace("_", " "), name)),
  );
  document.querySelectorAll("[data-opt]").forEach((input) => {
    const key = input.dataset.opt;
    input.value = state.opts[key];
  });
  $("#samples-out").textContent = state.opts.samples;
}

document.querySelectorAll("[data-opt]").forEach((input) => {
  const onChange = () => {
    const key = input.dataset.opt;
    const numeric = ["start", "end", "samples", "octaves", "bpm", "step"];
    state.opts[key] = numeric.includes(key) ? Number(input.value) : input.value;
    if (key === "samples") $("#samples-out").textContent = input.value;
    if (["start", "end"].includes(key)) autoFit = true;
    scheduleRender();
  };
  input.addEventListener("input", onChange);
  input.addEventListener("change", onChange);
});

$("#add-expr").addEventListener("click", () => {
  const expr = newExpr("");
  state.exprs.push(expr);
  renderExprs();
  document.querySelector("#exprs > li:last-child input")?.focus();
});

// ---------- rendering ----------

function scheduleRender(delay = 350) {
  clearTimeout(renderTimer);
  saveState();
  renderTimer = setTimeout(renderNow, delay);
}

async function renderNow() {
  const mine = ++renderSeq;
  const body = {
    expressions: state.exprs.map((e) => ({ src: e.src, waveform: e.waveform, enabled: e.enabled, invert: e.invert })),
    options: state.opts,
  };
  let data;
  try {
    const res = await fetch("/api/render", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    data = await res.json();
    if (!res.ok) throw new Error(data.error || res.statusText);
  } catch (error) {
    if (mine === renderSeq) setErrorLine(error.message);
    return;
  }
  if (mine !== renderSeq) return;
  applyRender(data);
}

function setErrorLine(message) {
  $("#errors").textContent = message;
}

function applyRender(data) {
  render = data;
  paintExprErrors(data.errors);

  if (data.audio) {
    const previous = audio.currentTime || 0;
    const wasPlaying = !audio.paused;
    audio.src = data.audio.url;
    audio.onloadedmetadata = () => {
      audio.currentTime = Math.min(previous, audio.duration || 0);
      if (wasPlaying) audio.play().catch(() => {});
    };
    $("#dl-wav").href = data.audio.url;
    $("#dl-wav").hidden = false;
    $("#dl-mp3").href = data.audio.url.replace(/\.wav$/, ".mp3");
    $("#dl-mp3").hidden = false;
  } else {
    audio.pause();
    audio.removeAttribute("src");
    audio.load();
    $("#dl-wav").hidden = true;
    $("#dl-mp3").hidden = true;
  }

  if (autoFit) view = fitView();
  $("#empty").hidden = data.voices.length > 0;
  if (data.voices.length === 0) {
    setErrorLine(data.errors.length ? "" : "Nothing to play yet.");
  } else {
    setErrorLine(data.errors.length ? `${data.errors.length} expression(s) skipped (see above).` : "");
  }
  dirty = true;
  updatePublishState();
  updatePlayButton();
}

function fitView() {
  const xs = [];
  const ys = [];
  for (const voice of render?.voices ?? []) {
    for (const s of voice.samples) {
      xs.push(s.x);
      if (s.y !== null) ys.push(s.y);
    }
  }
  if (!xs.length) return { xmin: -1, xmax: 1, ymin: -1, ymax: 1 };
  let xmin = Math.min(...xs);
  let xmax = Math.max(...xs);
  let ymin = ys.length ? Math.min(...ys) : -1;
  let ymax = ys.length ? Math.max(...ys) : 1;
  if (xmax === xmin) [xmin, xmax] = [xmin - 1, xmax + 1];
  if (ymax === ymin) [ymin, ymax] = [ymin - 1, ymax + 1];
  const pad = (ymax - ymin) * 0.1;
  return { xmin, xmax, ymin: ymin - pad, ymax: ymax + pad };
}

// ---------- canvas helpers ----------

function prepareCanvas(canvas) {
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

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function niceStep(range, count) {
  const raw = range / count;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const normalised = raw / magnitude;
  const factor = normalised < 1.5 ? 1 : normalised < 3 ? 2 : normalised < 7 ? 5 : 10;
  return factor * magnitude;
}

function ticks(min, max, count) {
  const step = niceStep(max - min, count);
  const values = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) {
    values.push(Math.abs(v) < step * 1e-9 ? 0 : v);
  }
  return { values, step };
}

const formatTick = (value, step) => value.toFixed(Math.max(0, Math.ceil(-Math.log10(step))));

function noteName(midi) {
  return `${NOTE_NAMES[((midi % 12) + 12) % 12]}${Math.floor(midi / 12) - 1}`;
}

function fmtTime(seconds) {
  const s = Number.isFinite(seconds) ? seconds : 0;
  const minutes = Math.floor(s / 60);
  return `${minutes}:${(s - minutes * 60).toFixed(1).padStart(4, "0")}`;
}

// ---------- graph ----------

const toPx = (x, w) => ((x - view.xmin) / (view.xmax - view.xmin)) * w;
const toPy = (y, h) => h - ((y - view.ymin) / (view.ymax - view.ymin)) * h;
const fromPx = (px, w) => view.xmin + (px / w) * (view.xmax - view.xmin);
const fromPy = (py, h) => view.ymin + ((h - py) / h) * (view.ymax - view.ymin);

function drawGraph(beat) {
  const { ctx, w, h } = prepareCanvas(graphCanvas);
  if (!view) view = fitView();

  const grid = cssVar("--line") || "#2a2f3a";
  const muted = cssVar("--muted") || "#8a92a3";
  const xt = ticks(view.xmin, view.xmax, 8);
  const yt = ticks(view.ymin, view.ymax, 6);

  ctx.font = "11px ui-monospace, Menlo, monospace";
  ctx.lineWidth = 1;
  ctx.strokeStyle = grid;
  ctx.beginPath();
  for (const v of xt.values) {
    const X = Math.round(toPx(v, w)) + 0.5;
    ctx.moveTo(X, 0);
    ctx.lineTo(X, h);
  }
  for (const v of yt.values) {
    const Y = Math.round(toPy(v, h)) + 0.5;
    ctx.moveTo(0, Y);
    ctx.lineTo(w, Y);
  }
  ctx.stroke();

  // axes through the origin, drawn stronger
  ctx.strokeStyle = muted;
  ctx.beginPath();
  if (view.ymin <= 0 && view.ymax >= 0) {
    const Y = Math.round(toPy(0, h)) + 0.5;
    ctx.moveTo(0, Y);
    ctx.lineTo(w, Y);
  }
  if (view.xmin <= 0 && view.xmax >= 0) {
    const X = Math.round(toPx(0, w)) + 0.5;
    ctx.moveTo(X, 0);
    ctx.lineTo(X, h);
  }
  ctx.stroke();

  ctx.fillStyle = muted;
  for (const v of xt.values) {
    ctx.fillText(formatTick(v, xt.step), toPx(v, w) + 3, h - 6);
  }
  for (const v of yt.values) {
    ctx.fillText(formatTick(v, yt.step), 6, toPy(v, h) - 4);
  }

  if (!render) return;

  // curves
  for (const voice of render.voices) {
    const color = PALETTE[voice.index % PALETTE.length];
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    let pen = false;
    for (const s of voice.samples) {
      if (s.y === null) {
        pen = false;
        continue;
      }
      const X = toPx(s.x, w);
      const Y = toPy(s.y, h);
      if (pen) ctx.lineTo(X, Y);
      else ctx.moveTo(X, Y);
      pen = true;
    }
    ctx.stroke();

    ctx.fillStyle = color;
    for (const s of voice.samples) {
      if (s.y === null) continue;
      ctx.beginPath();
      ctx.arc(toPx(s.x, w), toPy(s.y, h), 2.6, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  // playhead: ring on whichever sample is sounding now
  if (beat !== null && render.audio) {
    for (const voice of render.voices) {
      const s = sampleAtBeat(voice, beat);
      if (!s || s.y === null) continue;
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(toPx(s.x, w), toPy(s.y, h), 6, 0, Math.PI * 2);
      ctx.stroke();
    }
  }

  // hover marker
  if (hover && hover.sample.y !== null) {
    ctx.strokeStyle = cssVar("--text") || "#e6e8ee";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(toPx(hover.sample.x, w), toPy(hover.sample.y, h), 9, 0, Math.PI * 2);
    ctx.stroke();
  }
}

function sampleAtBeat(voice, beat) {
  for (const s of voice.samples) {
    if (beat >= s.start && beat < s.start + s.duration) return s;
  }
  return null;
}

function nearestSample(px, py, w, h) {
  let best = null;
  let bestDistance = 14;
  for (const voice of render?.voices ?? []) {
    for (const s of voice.samples) {
      if (s.y === null) continue;
      const dx = toPx(s.x, w) - px;
      const dy = toPy(s.y, h) - py;
      const distance = Math.hypot(dx, dy);
      if (distance < bestDistance) {
        bestDistance = distance;
        best = { voice, sample: s, px: toPx(s.x, w), py: toPy(s.y, h) };
      }
    }
  }
  return best;
}

function describeHover() {
  const readout = $("#readout");
  if (!hover) {
    readout.textContent = "Hover the graph to read values";
    return;
  }
  const { voice, sample } = hover;
  const note = sample.pitch === null ? "rest" : noteName(sample.pitch);
  const seconds = (sample.start * 60) / (render?.bpm || 120);
  readout.textContent = `y = ${voice.expression}  x = ${sample.x.toFixed(3)}  y = ${sample.y.toFixed(3)}  note ${note}  at ${fmtTime(seconds)}`;
}

function localPoint(event, canvas) {
  const rect = canvas.getBoundingClientRect();
  return { px: event.clientX - rect.left, py: event.clientY - rect.top, w: rect.width, h: rect.height };
}

graphCanvas.addEventListener("mousedown", (event) => {
  drag = { x: event.clientX, y: event.clientY, view: { ...view }, w: graphCanvas.clientWidth, h: graphCanvas.clientHeight };
  graphCanvas.classList.add("dragging");
});

window.addEventListener("mouseup", () => {
  drag = null;
  graphCanvas.classList.remove("dragging");
});

graphCanvas.addEventListener("mousemove", (event) => {
  const { px, py, w, h } = localPoint(event, graphCanvas);
  if (drag) {
    const dx = event.clientX - drag.x;
    const dy = event.clientY - drag.y;
    const xSpan = drag.view.xmax - drag.view.xmin;
    const ySpan = drag.view.ymax - drag.view.ymin;
    view = {
      xmin: drag.view.xmin - (dx / drag.w) * xSpan,
      xmax: drag.view.xmax - (dx / drag.w) * xSpan,
      ymin: drag.view.ymin + (dy / drag.h) * ySpan,
      ymax: drag.view.ymax + (dy / drag.h) * ySpan,
    };
    autoFit = false;
  }
  hover = nearestSample(px, py, w, h);
  describeHover();
  dirty = true;
});

graphCanvas.addEventListener("mouseleave", () => {
  hover = null;
  describeHover();
  dirty = true;
});

graphCanvas.addEventListener(
  "wheel",
  (event) => {
    event.preventDefault();
    const { px, py, w, h } = localPoint(event, graphCanvas);
    const cx = fromPx(px, w);
    const cy = fromPy(py, h);
    const factor = Math.exp(event.deltaY * 0.0015);
    view = {
      xmin: cx - (cx - view.xmin) * factor,
      xmax: cx + (view.xmax - cx) * factor,
      ymin: cy - (cy - view.ymin) * factor,
      ymax: cy + (view.ymax - cy) * factor,
    };
    autoFit = false;
    dirty = true;
  },
  { passive: false },
);

graphCanvas.addEventListener("dblclick", () => {
  autoFit = true;
  view = fitView();
  dirty = true;
});

$("#fit").addEventListener("click", () => {
  autoFit = true;
  view = fitView();
  dirty = true;
});

// ---------- piano roll ----------

function drawRoll(beat) {
  const { ctx, w, h } = prepareCanvas(rollCanvas);
  const padL = 46;
  const padR = 12;
  const padT = 10;
  const padB = 24;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;
  const muted = cssVar("--muted") || "#8a92a3";
  const grid = cssVar("--line") || "#2a2f3a";
  ctx.font = "11px ui-monospace, Menlo, monospace";

  const voices = render?.voices ?? [];
  const allSamples = voices.flatMap((v) => v.samples);
  const notes = voices.flatMap((v) => v.samples.filter((s) => s.pitch !== null).map((s) => ({ ...s, index: v.index })));
  if (!allSamples.length || !notes.length) {
    rollGeometry = null;
    ctx.fillStyle = muted;
    ctx.fillText("No notes yet", padL, h / 2);
    return;
  }

  const totalBeats = Math.max(...allSamples.map((s) => s.start + s.duration));
  const pitches = notes.map((n) => n.pitch);
  const low = Math.min(...pitches) - 1;
  const high = Math.max(...pitches) + 1;
  const rows = high - low + 1;
  const rowH = plotH / rows;
  const X = (b) => padL + (b / totalBeats) * plotW;
  const Y = (p) => padT + (high - p) * rowH;
  rollGeometry = { padL, plotW, totalBeats };

  // pitch rows, labelled at every C
  ctx.lineWidth = 1;
  for (let p = low; p <= high; p++) {
    const y = Math.round(Y(p)) + 0.5;
    ctx.strokeStyle = p % 12 === 0 ? muted : grid;
    ctx.globalAlpha = p % 12 === 0 ? 0.5 : 0.35;
    ctx.beginPath();
    ctx.moveTo(padL, y);
    ctx.lineTo(w - padR, y);
    ctx.stroke();
    ctx.globalAlpha = 1;
    if (p % 12 === 0) {
      ctx.fillStyle = muted;
      ctx.fillText(noteName(p), 6, y + 4);
    }
  }

  // notes
  for (const n of notes) {
    const x0 = X(n.start);
    const x1 = X(n.start + n.duration);
    ctx.fillStyle = PALETTE[n.index % PALETTE.length];
    ctx.globalAlpha = 0.85;
    ctx.fillRect(x0, Y(n.pitch) + 1, Math.max(2, x1 - x0 - 1), Math.max(2, rowH - 2));
  }
  ctx.globalAlpha = 1;

  // time axis
  const secondsPerBeat = 60 / (render?.bpm || 120);
  const totalSeconds = totalBeats * secondsPerBeat;
  const tt = ticks(0, totalSeconds, 8);
  ctx.fillStyle = muted;
  for (const s of tt.values) {
    const x = Math.round(X(s / secondsPerBeat)) + 0.5;
    ctx.strokeStyle = grid;
    ctx.beginPath();
    ctx.moveTo(x, padT + plotH);
    ctx.lineTo(x, padT + plotH + 4);
    ctx.stroke();
    ctx.fillText(`${formatTick(s, tt.step)}s`, x + 2, h - 6);
  }

  // playhead
  if (beat !== null && render.audio) {
    const x = X(beat);
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(x, padT);
    ctx.lineTo(x, padT + plotH);
    ctx.stroke();
  }
}

rollCanvas.addEventListener("click", (event) => {
  if (!rollGeometry || !render?.audio) return;
  const rect = rollCanvas.getBoundingClientRect();
  const fraction = (event.clientX - rect.left - rollGeometry.padL) / rollGeometry.plotW;
  const beat = Math.min(Math.max(fraction, 0), 1) * rollGeometry.totalBeats;
  audio.currentTime = (beat * 60) / (render.bpm || 120);
  dirty = true;
});

// ---------- transport and animation loop ----------

const playButton = $("#play");

function updatePlayButton() {
  const playing = !audio.paused && !audio.ended;
  playButton.textContent = playing ? "❚❚" : "▶";
  playButton.setAttribute("aria-label", playing ? "Pause" : "Play");
  playButton.disabled = !render?.audio;
}

function togglePlay() {
  if (!render?.audio) return;
  if (audio.paused) audio.play().catch(() => {});
  else audio.pause();
}

playButton.addEventListener("click", togglePlay);
audio.addEventListener("play", updatePlayButton);
audio.addEventListener("pause", updatePlayButton);
audio.addEventListener("ended", updatePlayButton);

document.addEventListener("keydown", (event) => {
  if (event.code !== "Space") return;
  if (event.target.closest("input, textarea, select, button")) return;
  event.preventDefault();
  togglePlay();
});

window.addEventListener("resize", () => {
  dirty = true;
});

let lastBeat = null;
function frame() {
  const bpm = render?.bpm || state.opts.bpm || 120;
  const seconds = audio.currentTime || 0;
  const beat = render?.audio ? (seconds * bpm) / 60 : null;
  $("#time").textContent = `${fmtTime(seconds)} / ${fmtTime(render?.duration || 0)}`;
  if (dirty || beat !== lastBeat) {
    drawGraph(beat);
    drawRoll(beat);
    dirty = false;
    lastBeat = beat;
  }
  requestAnimationFrame(frame);
}

// ---------- publishing ----------

function defaultTitle() {
  const names = state.exprs.filter((e) => e.enabled && e.src.trim()).map((e) => e.src.trim());
  return names.join(" + ").slice(0, 200) || "mathmusic";
}

function setPublishMessage(text, kind = "") {
  const node = $("#pub-message");
  node.textContent = text;
  node.className = `message ${kind}`;
}

function updatePublishState() {
  const button = $("#publish");
  const hint = $("#publish-hint");
  const canPublish = serverStatus.plyrfm && serverStatus.plyr_token && Boolean(render?.audio);
  button.disabled = !canPublish;
  if (!serverStatus.plyrfm) {
    hint.textContent = "The plyrfm package is not installed: uv pip install plyrfm==0.0.1a25";
  } else if (!serverStatus.plyr_token) {
    hint.textContent = "Set PLYR_TOKEN and restart mathmusic to publish. Create a token at plyr.fm/settings#developer. Your account needs an artist profile.";
  } else if (!render?.audio) {
    hint.textContent = "Render something first. The published track is the current render as an MP3.";
  } else {
    hint.textContent = "Uploads the current render as an MP3 to your plyr.fm account.";
  }
  if (!$("#pub-title").value) $("#pub-title").placeholder = defaultTitle();
}

$("#publish").addEventListener("click", async () => {
  if (!render?.audio) return;
  const payload = {
    render_id: render.audio.id,
    title: $("#pub-title").value.trim() || defaultTitle(),
    album: $("#pub-album").value,
    tags: $("#pub-tags").value,
    description: $("#pub-desc").value,
  };
  const button = $("#publish");
  button.disabled = true;
  setPublishMessage("Uploading to plyr.fm… this can take a minute.");
  try {
    const res = await fetch("/api/publish", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || res.statusText);
    setPublishMessage(`Published to plyr.fm as track ${data.track_id}.`, "ok");
  } catch (error) {
    setPublishMessage(error.message, "err");
  } finally {
    updatePublishState();
  }
});

// ---------- status pills ----------

function renderStatus() {
  const pills = [
    ["ffmpeg (MP3)", serverStatus.ffmpeg],
    ["plyrfm SDK", serverStatus.plyrfm],
    ["PLYR_TOKEN", serverStatus.plyr_token],
  ];
  $("#status").replaceChildren(
    ...pills.map(([label, ok]) => {
      const pill = document.createElement("span");
      pill.className = `pill ${ok ? "ok" : "no"}`;
      pill.textContent = `${ok ? "✓" : "✕"} ${label}`;
      return pill;
    }),
  );
}

async function loadStatus() {
  try {
    serverStatus = await (await fetch("/api/status")).json();
  } catch {
    serverStatus = { ffmpeg: false, plyrfm: false, plyr_token: false };
  }
  renderStatus();
  updatePublishState();
}

async function loadCatalogue() {
  try {
    catalogue = await (await fetch("/api/instruments")).json();
    renderExprs();
  } catch {
    /* the selector still offers auto; instruments simply will not be listed */
  }
}

// ---------- boot ----------

renderPresets();
syncOptionInputs();
renderExprs();
loadCatalogue();
loadStatus();
scheduleRender(0);
updatePlayButton();
requestAnimationFrame(frame);
