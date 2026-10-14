// The bottom panel: Clip, Track, Effects, Automation, Master and Publish tabs.
//
// Each tab is built once. Fields are bound to the model through get/set
// closures, and sync() copies model values back into fields that are not
// being edited.

import { api } from "./api.js";
import { trackColor, view } from "./arrange.js";
import { FormulaPlot, drawClipGraph, pitchTable } from "./graphs.js";
import {
  clipRender,
  edit,
  errorsFor,
  findClip,
  live,
  select,
  selectedClip,
  selectedTrack,
  settle,
  state,
  subscribe,
} from "./store.js";
import { currentBeat, isPlaying } from "./transport.js";
import { $, clamp, cssVar, el, noteName, parseNote, prepareCanvas, setValue, uid } from "./util.js";

// ---------------------------------------------------------------- field helpers

class Bindings {
  constructor() {
    this.list = [];
  }
  add(fn) {
    this.list.push(fn);
  }
  sync() {
    for (const fn of this.list) fn();
  }
}

function field(label, control, hint) {
  return el("label", { class: "field" }, el("span", { class: "field-label" }, label), control, hint && el("span", { class: "hint" }, hint));
}

function numberInput(bind, { get, set, min, max, step = "any", integer = false }) {
  const input = el("input", { type: "number", step, min, max });
  input.addEventListener("input", () => {
    const value = Number(input.value);
    const ok =
      input.value.trim() !== "" &&
      Number.isFinite(value) &&
      (min === undefined || value >= min) &&
      (max === undefined || value <= max) &&
      (!integer || Number.isInteger(value));
    input.classList.toggle("invalid", !ok);
    if (ok) live(() => set(value));
  });
  input.addEventListener("change", () => {
    input.classList.remove("invalid");
    settle();
    const value = get();
    input.value = typeof value === "number" ? String(Number(value.toFixed(6))) : (value ?? "");
  });
  bind.add(() => setValue(input, get()));
  return input;
}

function rangeInput(bind, { get, set, min, max, step, format, toSlider = (v) => v, fromSlider = (v) => v }) {
  const input = el("input", { type: "range", min, max, step });
  const out = el("output", { class: "readout" });
  input.addEventListener("input", () => {
    const value = fromSlider(Number(input.value));
    live(() => set(value));
    out.textContent = format(value);
  });
  input.addEventListener("change", settle);
  bind.add(() => {
    setValue(input, toSlider(get()));
    out.textContent = format(get());
  });
  return el("span", { class: "range-row" }, input, out);
}

function textInput(bind, { get, set, placeholder = "", mono = true, maxlength = 300 }) {
  const input = el("input", {
    type: "text",
    class: mono ? "mono" : "",
    placeholder,
    maxlength,
    spellcheck: false,
    autocomplete: "off",
  });
  input.addEventListener("input", () => live(() => set(input.value)));
  input.addEventListener("change", settle);
  bind.add(() => setValue(input, get() ?? ""));
  return input;
}

function selectInput(bind, options, { get, set }) {
  const select = el("select", {}, options.map(([value, label]) => el("option", { value }, label)));
  select.addEventListener("change", () => edit(() => set(select.value)));
  bind.add(() => setValue(select, get()));
  return select;
}

function checkInput(bind, label, { get, set }) {
  const input = el("input", { type: "checkbox" });
  input.addEventListener("change", () => edit(() => set(input.checked)));
  bind.add(() => setValue(input, get()));
  return el("label", { class: "check" }, input, label);
}

function errorLine(bind, getMessages) {
  const node = el("div", { class: "field-error", role: "alert" });
  bind.add(() => {
    node.textContent = getMessages().map((e) => e.error).join(" · ");
  });
  return node;
}

// ---------------------------------------------------------------- sounds

const DEFAULT_CYCLE = ["sine", "triangle", "saw", "square"];

function soundFormula(track, index) {
  const cat = state.catalogue;
  const spec = track.sound;
  const name = spec || DEFAULT_CYCLE[index % DEFAULT_CYCLE.length];
  const wave = cat.waveforms.find((w) => w.name === name);
  if (wave) return { wave: wave.formula, envelope: null };
  const inst = cat.instruments.find((i) => i.name === name);
  if (inst) return { wave: inst.wave, envelope: inst.envelope };
  return { wave: spec, envelope: null };
}

function isNamedSound(spec) {
  const cat = state.catalogue;
  return !spec || cat.waveforms.some((w) => w.name === spec) || cat.instruments.some((i) => i.name === spec);
}

// ---------------------------------------------------------------- effects editor

function effectChain(getChain, errorWhere) {
  const root = el("div", { class: "fx-chain" });
  const list = el("div", { class: "fx-list" });
  const add = el("select", { class: "fx-add", "aria-label": "Add effect" });
  add.addEventListener("change", () => {
    const type = add.value;
    add.value = "";
    if (!type) return;
    const spec = state.catalogue.effects[type];
    const params = Object.fromEntries(Object.entries(spec).map(([name, p]) => [name, p.default]));
    edit(() => getChain()?.push({ type, bypass: false, params }));
  });
  root.append(list, add);

  let signature = "";
  let cards = [];

  function rebuild(chain) {
    list.replaceChildren();
    cards = chain.map((effect, index) => card(effect.type, index));
    list.append(...cards.map((c) => c.root));
    if (!chain.length) list.append(el("p", { class: "hint" }, "No effects. Add one below; they run top to bottom."));
  }

  function card(type, index) {
    const bind = new Bindings();
    const fx = () => getChain()?.[index];
    const spec = state.catalogue.effects[type] ?? {};
    const move = (delta) =>
      edit(() => {
        const chain = getChain();
        const target = index + delta;
        if (target < 0 || target >= chain.length) return;
        [chain[index], chain[target]] = [chain[target], chain[index]];
      });
    const params = Object.entries(spec).map(([name, p]) => {
      if (p.kind === "formula") {
        const canvas = el("canvas", { class: "mini-plot" });
        const plotter = new FormulaPlot(canvas, { color: "#facc15", xLabel: "in" });
        bind.add(() => {
          if (!fx()) return;
          plotter.show(fx().params[name], -1.5, 1.5);
        });
        return el(
          "div",
          { class: "fx-param formula" },
          field(`${name} (x = sample value)`, textInput(bind, { get: () => fx()?.params[name], set: (v) => (fx().params[name] = v) })),
          canvas,
        );
      }
      const log = name === "cutoff";
      const format =
        name === "cutoff" ? (v) => `${Math.round(v)} Hz` : name === "time" ? (v) => `${v.toFixed(3)} beats` : (v) => v.toFixed(2);
      return el(
        "div",
        { class: "fx-param" },
        field(
          name,
          rangeInput(bind, {
            get: () => fx()?.params[name] ?? p.default,
            set: (v) => (fx().params[name] = v),
            min: log ? Math.log(p.min) : p.min,
            max: log ? Math.log(p.max) : p.max,
            step: log ? 0.001 : (p.max - p.min) / 400,
            format,
            toSlider: log ? Math.log : (v) => v,
            fromSlider: log ? (v) => Math.round(Math.exp(v)) : (v) => Number(v.toFixed(4)),
          }),
        ),
      );
    });
    const bypass = checkInput(bind, "bypass", { get: () => fx()?.bypass, set: (v) => (fx().bypass = v) });
    const root = el(
      "div",
      { class: "fx-card" },
      el(
        "div",
        { class: "fx-head" },
        el("strong", {}, type),
        bypass,
        el("span", { class: "spacer" }),
        el("button", { class: "icon", type: "button", title: "Move up", onclick: () => move(-1) }, "↑"),
        el("button", { class: "icon", type: "button", title: "Move down", onclick: () => move(1) }, "↓"),
        el(
          "button",
          { class: "icon remove", type: "button", title: "Remove effect", onclick: () => edit(() => getChain().splice(index, 1)) },
          "×",
        ),
      ),
      el("div", { class: "fx-params" }, params),
      errorLine(bind, () => errorWhere().filter((e) => e.field === `effects[${index}]`)),
    );
    return { root, bind };
  }

  function sync() {
    const chain = getChain();
    if (!chain) return;
    add.replaceChildren(
      el("option", { value: "" }, "+ Add effect…"),
      ...Object.keys(state.catalogue.effects).map((type) => el("option", { value: type }, type)),
    );
    const next = chain.map((e) => e.type).join(",");
    if (next !== signature) {
      signature = next;
      rebuild(chain);
    }
    for (const c of cards) c.bind.sync();
  }

  return { root, sync, reset: () => (signature = "\u0000") };
}

// ---------------------------------------------------------------- tabs

const TABS = [
  ["clip", "Clip"],
  ["track", "Track"],
  ["effects", "Effects"],
  ["automation", "Automation"],
  ["mixer", "Mixer"],
  ["master", "Master"],
  ["publish", "Publish"],
];
export const TAB_ORDER = TABS.map(([key]) => key);

let current = "clip";
const views = {};

function emptyHint(text) {
  return el("div", { class: "empty-hint" }, text);
}

function buildClipTab() {
  const bind = new Bindings();
  const clip = () => selectedClip();
  const set = (key) => (v) => (clip()[key] = v);
  const get = (key) => () => clip()?.[key];

  const expression = textInput(bind, { get: get("expression"), set: set("expression"), placeholder: "y = f(x), e.g. sin(x)" });
  expression.classList.add("big");
  expression.id = "clip-expression";

  const fixed = el("input", { type: "checkbox" });
  fixed.addEventListener("change", () =>
    edit(() => {
      const c = clip();
      if (fixed.checked) {
        const bounds = clipRender(c.id)?.bounds ?? [-1, 1];
        c.y_min = Number(bounds[0].toFixed(4));
        c.y_max = Number(bounds[1] > bounds[0] ? bounds[1].toFixed(4) : (bounds[0] + 1).toFixed(4));
      } else {
        c.y_min = null;
        c.y_max = null;
      }
    }),
  );
  const yMin = numberInput(bind, { get: get("y_min"), set: set("y_min"), min: -1e9, max: 1e9 });
  const yMax = numberInput(bind, { get: get("y_max"), set: set("y_max"), min: -1e9, max: 1e9 });
  bind.add(() => {
    const c = clip();
    if (!c) return;
    setValue(fixed, c.y_min !== null);
    yMin.disabled = c.y_min === null;
    yMax.disabled = c.y_min === null;
  });

  const splitMessage = el("p", { class: "hint" });
  bind.add(() => (splitMessage.textContent = ""));
  const octaveOptions = [-3, -2, -1, 0, 1, 2, 3].map((o) => [String(o), o > 0 ? `+${o}` : String(o)]);
  const form = el(
    "div",
    { class: "clip-form" },
    field("y = f(x)", expression),
    errorLine(bind, () => (clip() ? errorsFor(selectedTrack()?.id, clip().id) : [])),
    el(
      "div",
      { class: "grid2" },
      field("x from", numberInput(bind, { get: get("x_start"), set: set("x_start"), min: -1e6, max: 1e6 })),
      field("x to", numberInput(bind, { get: get("x_end"), set: set("x_end"), min: -1e6, max: 1e6 })),
      field("Notes (samples of the curve)", numberInput(bind, { get: get("notes"), set: set("notes"), min: 1, max: 1024, step: 1, integer: true })),
      field("Rhythm", selectInput(bind, [["uniform", "uniform"], ["slope", "follow slope"]], { get: get("rhythm"), set: set("rhythm") })),
      field("Start (beat)", numberInput(bind, { get: get("start"), set: set("start"), min: 0, max: 2048 })),
      field("Length (beats)", numberInput(bind, { get: get("length"), set: set("length"), min: 0.25, max: 2048 })),
      field("Octave", selectInput(bind, octaveOptions, { get: () => String(clip()?.octave ?? 0), set: (v) => (clip().octave = Number(v)) })),
      field("Range (octaves)", selectInput(bind, ["1", "2", "3", "4"].map((o) => [o, o]), { get: () => String(clip()?.octaves ?? 2), set: (v) => (clip().octaves = Number(v)) })),
      field("Gate", rangeInput(bind, { get: get("gate"), set: set("gate"), min: 0.05, max: 1, step: 0.01, format: (v) => `${Math.round(v * 100)}%` })),
      field("Gain", rangeInput(bind, { get: get("gain"), set: set("gain"), min: 0, max: 2, step: 0.01, format: (v) => v.toFixed(2) })),
    ),
    el(
      "div",
      { class: "row-fields" },
      checkInput(bind, "Invert (high values sound low)", { get: get("invert"), set: set("invert") }),
    ),
    el(
      "div",
      { class: "grid2 y-range" },
      el("label", { class: "check span2" }, fixed, "Fixed y range (otherwise the curve's own min and max)"),
      field("y at lowest note", yMin),
      field("y at highest note", yMax),
    ),
    field("Clip name", textInput(bind, { get: get("name"), set: set("name"), mono: false, maxlength: 80, placeholder: "optional" })),
    el(
      "div",
      { class: "row-fields" },
      el("button", { class: "ghost", type: "button", onclick: duplicateClip }, "Duplicate (⌘D)"),
      el(
        "button",
        {
          class: "ghost",
          type: "button",
          title: "Split the clip where the playhead is",
          onclick: () => {
            const problem = splitClip();
            if (problem) splitMessage.textContent = problem;
          },
        },
        "Split at playhead (⌘E)",
      ),
      el("button", { class: "ghost danger", type: "button", onclick: deleteClip }, "Delete (⌫)"),
    ),
    splitMessage,
  );

  const canvas = el("canvas", { class: "clip-graph", "aria-label": "Graph of the clip's curve and the notes it plays" });
  const readout = el("div", { class: "readout graph-readout" }, "Hover the curve to read values");
  let hover = null;
  let geometry = null;
  canvas.addEventListener("mousemove", (event) => {
    const data = clipRender(clip()?.id);
    if (!geometry || !data?.samples?.length) return;
    const rect = canvas.getBoundingClientRect();
    const px = event.clientX - rect.left;
    let best = null;
    let bestDistance = Infinity;
    for (const s of data.samples) {
      const d = Math.abs(geometry.X(s.x) - px);
      if (d < bestDistance) {
        best = s;
        bestDistance = d;
      }
    }
    hover = best && best.y !== null ? best : null;
    readout.textContent = best
      ? `x = ${best.x.toFixed(3)}   y = ${best.y === null ? "undefined" : best.y.toFixed(3)}   ` +
        `${best.pitch === null ? "rest" : `note ${noteName(best.pitch)}`}   beat ${best.start.toFixed(2)}`
      : "";
    drawGraph();
  });
  canvas.addEventListener("mouseleave", () => {
    hover = null;
    readout.textContent = "Hover the curve to read values";
    drawGraph();
  });

  function drawGraph() {
    const c = clip();
    const data = c && clipRender(c.id);
    if (!c || !data) return;
    const project = state.project;
    const degrees = state.catalogue.scales[project.scale] ?? [0];
    const root = (parseNote(project.root) ?? 60) + 12 * c.octave;
    const found = findClip(c.id);
    const index = state.project.tracks.indexOf(found.track);
    geometry = drawClipGraph(canvas, {
      samples: data.samples,
      bounds: data.bounds ?? [0, 1],
      pitches: pitchTable(degrees, root, c.octaves),
      invert: c.invert,
      color: trackColor(index),
      playBeat: isPlaying() || currentBeat() > 0 ? currentBeat() : null,
      hover,
    });
  }

  const hint = emptyHint("Select a clip, or double-click a lane to create one. Each clip plays a curve y = f(x): x runs across the clip, y sets the pitch.");
  const body = el("div", { class: "clip-editor" }, form, el("div", { class: "graph-col" }, canvas, readout));
  const root = el("div", { class: "tab-body" }, hint, body);

  return {
    root,
    sync(reason) {
      const has = Boolean(clip());
      hint.hidden = has;
      body.hidden = !has;
      if (!has) return;
      if (reason !== "frame") bind.sync();
      drawGraph();
    },
    focus() {
      expression.focus();
      expression.select();
    },
  };
}

function duplicateClip() {
  const found = findClip(state.selection.clip);
  if (!found) return;
  const copy = { ...structuredClone(found.clip), id: uid("c"), start: found.clip.start + found.clip.length };
  edit(() => found.track.clips.push(copy));
  select(found.track.id, copy.id);
}

function deleteClip() {
  const found = findClip(state.selection.clip);
  if (!found) return;
  edit(() => found.track.clips.splice(found.track.clips.indexOf(found.clip), 1));
  select(found.track.id, null);
}

/**
 * Split the selected clip at a beat. Each half keeps its share of the x range
 * and of the notes. An automatic y range is pinned to the original curve's
 * range so the halves keep their pitches. Returns an error message or null.
 */
function splitClip(at = currentBeat()) {
  const found = findClip(state.selection.clip);
  if (!found) return "Select a clip to split.";
  const c = found.clip;
  const beat = Math.round(at / view.snap) * view.snap; // audio time is not exact; split on the grid
  if (beat <= c.start + 0.01 || beat >= c.start + c.length - 0.01) return "Move the playhead inside the selected clip to split it.";
  const fraction = (beat - c.start) / c.length;
  const xMid = c.x_start + fraction * (c.x_end - c.x_start);
  const leftNotes = Math.max(1, Math.round(c.notes * fraction));
  const rightNotes = Math.max(1, c.notes - leftNotes);
  const bounds = clipRender(c.id)?.bounds;
  const pin = c.y_min === null && bounds && bounds[1] > bounds[0];
  const right = {
    ...structuredClone(c),
    id: uid("c"),
    start: beat,
    length: c.start + c.length - beat,
    x_start: xMid,
    notes: rightNotes,
  };
  edit(() => {
    if (pin) {
      [c.y_min, c.y_max] = bounds;
      [right.y_min, right.y_max] = bounds;
    }
    c.length = beat - c.start;
    c.x_end = xMid;
    c.notes = leftNotes;
    found.track.clips.push(right);
  });
  select(found.track.id, right.id);
  return null;
}

export const clipActions = { duplicateClip, deleteClip, splitClip };

function buildTrackTab() {
  const bind = new Bindings();
  const track = () => selectedTrack();
  const index = () => state.project.tracks.indexOf(track());

  const sound = el("select", { "aria-label": "Sound" });
  const custom = textInput(bind, {
    get: () => (isNamedSound(track()?.sound) ? "" : track()?.sound),
    set: (v) => (track().sound = v),
    placeholder: "one cycle in x, e.g. sin(2*pi*x) + 0.3*sin(6*pi*x)",
  });
  sound.addEventListener("change", () =>
    edit(() => {
      const t = track();
      if (sound.value === "__custom__") t.sound = isNamedSound(t.sound) ? "sin(2*pi*x) + 0.3*sin(6*pi*x)" : t.sound;
      else t.sound = sound.value === "auto" ? null : sound.value;
    }),
  );
  bind.add(() => {
    const t = track();
    if (!t) return;
    const cat = state.catalogue;
    if (sound.options.length !== 2 + cat.waveforms.length + cat.instruments.length) {
      sound.replaceChildren(
        el("option", { value: "auto" }, "auto (by track number)"),
        el("optgroup", { label: "Waveforms" }, cat.waveforms.map((w) => el("option", { value: w.name }, w.name))),
        el("optgroup", { label: "Instruments" }, cat.instruments.map((i) => el("option", { value: i.name, title: i.description }, i.name))),
        el("option", { value: "__custom__" }, "custom formula…"),
      );
    }
    setValue(sound, t.sound === null ? "auto" : isNamedSound(t.sound) ? t.sound : "__custom__");
    custom.hidden = isNamedSound(t.sound);
  });
  const description = el("p", { class: "hint" });
  bind.add(() => {
    const inst = state.catalogue.instruments.find((i) => i.name === track()?.sound);
    description.textContent = inst ? inst.description : "";
  });

  const envelope = textInput(bind, {
    get: () => track()?.envelope,
    set: (v) => (track().envelope = v.trim() ? v : null),
    placeholder: "instrument default; e.g. exp(-4*x) or min(1, 20*x)",
  });

  const waveCanvas = el("canvas", { class: "mini-plot" });
  const envCanvas = el("canvas", { class: "mini-plot" });
  const wavePlot = new FormulaPlot(waveCanvas, { color: "#25f4ee", xLabel: "phase", yRange: null });
  const envPlot = new FormulaPlot(envCanvas, { color: "#a855f7", xLabel: "note" });
  bind.add(() => {
    const t = track();
    if (!t) return;
    const formulas = soundFormula(t, index());
    wavePlot.show(formulas.wave, 0, 1);
    envPlot.show(t.envelope || formulas.envelope, 0, 1, { fallback: "1" });
  });

  const form = el(
    "div",
    { class: "track-form" },
    field("Name", textInput(bind, { get: () => track()?.name, set: (v) => (track().name = v), mono: false, maxlength: 80 })),
    field("Sound", sound),
    custom,
    description,
    errorLine(bind, () => (track() ? errorsFor(track().id, null).filter((e) => e.field === "sound") : [])),
    field("Envelope over each note (x = 0 at the start, 1 at the end)", envelope),
    el(
      "div",
      { class: "grid2" },
      field("Volume (dB)", numberInput(bind, { get: () => track()?.volume_db, set: (v) => (track().volume_db = v), min: -60, max: 12, step: 0.5 })),
      field("Pan (−1 left … 1 right)", numberInput(bind, { get: () => track()?.pan, set: (v) => (track().pan = v), min: -1, max: 1, step: 0.05 })),
    ),
    el(
      "div",
      { class: "row-fields" },
      checkInput(bind, "Mute", { get: () => track()?.mute, set: (v) => (track().mute = v) }),
      checkInput(bind, "Solo", { get: () => track()?.solo, set: (v) => (track().solo = v) }),
      el("span", { class: "spacer" }),
      el("button", { class: "ghost small", type: "button", onclick: () => moveTrack(-1) }, "Move up"),
      el("button", { class: "ghost small", type: "button", onclick: () => moveTrack(1) }, "Move down"),
    ),
  );
  function moveTrack(delta) {
    const t = track();
    if (!t) return;
    edit((p) => {
      const from = p.tracks.indexOf(t);
      const to = from + delta;
      if (to < 0 || to >= p.tracks.length) return;
      [p.tracks[from], p.tracks[to]] = [p.tracks[to], p.tracks[from]];
    });
  }
  const graphs = el(
    "div",
    { class: "graph-col two" },
    el("div", {}, el("div", { class: "graph-title" }, "Waveform: one cycle"), waveCanvas),
    el("div", {}, el("div", { class: "graph-title" }, "Envelope: one note"), envCanvas),
  );
  const hint = emptyHint("Select a track to edit its sound.");
  const body = el("div", { class: "split" }, form, graphs);
  return {
    root: el("div", { class: "tab-body" }, hint, body),
    sync(reason) {
      const has = Boolean(track());
      hint.hidden = has;
      body.hidden = !has;
      if (has && reason !== "frame") bind.sync();
    },
  };
}

function buildEffectsTab() {
  const track = () => selectedTrack();
  const chain = effectChain(
    () => track()?.effects,
    () => (track() ? errorsFor(track().id, null) : []),
  );
  const title = el("h3", { class: "tab-title" });
  const hint = emptyHint("Select a track to edit its effects.");
  const body = el("div", {}, title, chain.root);
  let lastTrack = null;
  return {
    root: el("div", { class: "tab-body" }, hint, body),
    sync(reason) {
      const t = track();
      hint.hidden = Boolean(t);
      body.hidden = !t;
      if (!t || reason === "frame") return;
      if (t.id !== lastTrack) {
        lastTrack = t.id;
        chain.reset();
      }
      title.textContent = `Effects on ${t.name}`;
      chain.sync();
    },
  };
}

const AUTOMATION_EXAMPLES = {
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

function buildAutomationTab() {
  const bind = new Bindings();
  const track = () => selectedTrack();
  const length = () => Math.max(16, ...state.project.tracks.flatMap((t) => t.clips.map((c) => c.start + c.length)));

  function lane(key, label, color, describe) {
    const input = textInput(bind, {
      get: () => track()?.automation?.[key],
      set: (v) => {
        const t = track();
        t.automation = t.automation ?? { gain: null, pan: null };
        t.automation[key] = v.trim() ? v : null;
      },
      placeholder: key === "gain" ? "e.g. min(1, x/8)  (empty: no automation)" : "e.g. sin(2*pi*x/8)",
    });
    const canvas = el("canvas", { class: "mini-plot wide" });
    const plotter = new FormulaPlot(canvas, { color, xLabel: "beat", points: 400 });
    bind.add(() => {
      if (!track()) return;
      const formula = track().automation?.[key];
      const marker = isPlaying() || currentBeat() > 0 ? Math.round(currentBeat() * 4) / 4 : null;
      plotter.show(formula, 0, length(), { marker, fallback: key === "gain" ? "1" : "0" });
    });
    const examples = el(
      "div",
      { class: "chips" },
      AUTOMATION_EXAMPLES[key].map(([name, formula]) =>
        el(
          "button",
          {
            class: "chip",
            type: "button",
            title: formula,
            onclick: () =>
              edit(() => {
                const t = track();
                t.automation = { ...(t.automation ?? { gain: null, pan: null }), [key]: formula };
              }),
          },
          name,
        ),
      ),
      el(
        "button",
        {
          class: "chip",
          type: "button",
          onclick: () => edit(() => (track().automation = { ...(track().automation ?? {}), [key]: null })),
        },
        "clear",
      ),
    );
    return el(
      "div",
      { class: "automation-lane" },
      field(label, input, describe),
      examples,
      errorLine(bind, () => (track() ? errorsFor(track().id, null).filter((e) => e.field === `automation.${key}`) : [])),
      canvas,
    );
  }

  const hint = emptyHint("Select a track to automate it.");
  const body = el(
    "div",
    { class: "split" },
    lane("gain", "Gain × f(x)", "#34d399", "x is the song position in beats; the result multiplies the volume (0 to 4)."),
    lane("pan", "Pan + f(x)", "#60a5fa", "added to the track's pan and clipped to −1 … 1."),
  );
  return {
    root: el("div", { class: "tab-body" }, hint, body),
    sync(reason) {
      const has = Boolean(track());
      hint.hidden = has;
      body.hidden = !has;
      if (!has) return;
      if (reason !== "frame") bind.sync();
    },
  };
}

// ---------------------------------------------------------------- mixer

/** Peak level around a beat, from the rendered level data. */
function levelAt(peaks, beat) {
  const perBeat = state.render?.peaks_per_beat ?? 8;
  if (!peaks?.length || beat === null) return 0;
  const i = Math.floor(beat * perBeat);
  let level = 0;
  for (let k = i - 1; k <= i + 1; k++) if (k >= 0 && k < peaks.length) level = Math.max(level, peaks[k]);
  return level;
}

const METER_FLOOR_DB = -48;

function drawMeter(canvas, level) {
  const { ctx, w, h } = prepareCanvas(canvas);
  ctx.fillStyle = cssVar("--panel-3", "#222226");
  ctx.fillRect(0, 0, w, h);
  const db = level > 0 ? 20 * Math.log10(level) : -Infinity;
  const fraction = clamp((db - METER_FLOOR_DB) / -METER_FLOOR_DB, 0, 1);
  const gradient = ctx.createLinearGradient(0, h, 0, 0);
  gradient.addColorStop(0, "#34d399");
  gradient.addColorStop(0.75, "#facc15");
  gradient.addColorStop(1, "#fe2c55");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, h * (1 - fraction), w, h * fraction);
  ctx.fillStyle = "rgba(0,0,0,0.55)";
  for (let mark = -12; mark > METER_FLOOR_DB; mark -= 12) {
    ctx.fillRect(0, Math.round(h * (mark / METER_FLOOR_DB)), w, 1);
  }
}

function buildMixerTab() {
  const row = el("div", { class: "mixer" });
  let signature = "";
  let strips = [];

  function fader({ get, set }) {
    const input = el("input", { type: "range", class: "fader", min: -60, max: 12, step: 0.5, "aria-label": "Volume" });
    const out = el("output", { class: "readout" });
    input.addEventListener("input", () => live(() => set(Number(input.value))));
    input.addEventListener("change", settle);
    input.addEventListener("dblclick", () => edit(() => set(0)));
    return {
      nodes: [input, out],
      update() {
        setValue(input, get());
        const db = get();
        out.textContent = db <= -60 ? "-∞" : `${db > 0 ? "+" : ""}${db.toFixed(1)}`;
      },
    };
  }

  function trackStrip(id, index) {
    const track = () => state.project.tracks.find((t) => t.id === id);
    const meter = el("canvas", { class: "meter", "aria-hidden": "true" });
    const volume = fader({ get: () => track()?.volume_db ?? 0, set: (v) => (track().volume_db = v) });
    const pan = el("input", { type: "range", class: "pan", min: -1, max: 1, step: 0.05, "aria-label": "Pan", title: "Pan (double-click to centre)" });
    pan.addEventListener("input", () => live(() => (track().pan = Number(pan.value))));
    pan.addEventListener("change", settle);
    pan.addEventListener("dblclick", () => edit(() => (track().pan = 0)));
    const mute = el("button", { class: "ms mute", type: "button", onclick: () => edit(() => (track().mute = !track().mute)) }, "M");
    const solo = el("button", { class: "ms solo", type: "button", onclick: () => edit(() => (track().solo = !track().solo)) }, "S");
    const name = el("button", { class: "strip-name", type: "button", onclick: () => select(id, null) });
    const root = el(
      "div",
      { class: "strip" },
      name,
      el("div", { class: "strip-body" }, meter, el("div", { class: "fader-col" }, ...volume.nodes)),
      pan,
      el("div", { class: "row-fields center" }, mute, solo),
    );
    root.style.setProperty("--track-color", trackColor(index));
    return {
      root,
      update() {
        const t = track();
        if (!t) return;
        name.textContent = t.name;
        root.classList.toggle("selected", t.id === state.selection.track);
        volume.update();
        setValue(pan, t.pan);
        mute.classList.toggle("on", t.mute);
        solo.classList.toggle("on", t.solo);
      },
      meter(beat) {
        const peaks = state.render?.tracks.find((t) => t.id === id)?.peaks;
        drawMeter(meter, levelAt(peaks, beat));
      },
    };
  }

  function masterStrip() {
    const meter = el("canvas", { class: "meter", "aria-hidden": "true" });
    const volume = fader({ get: () => state.project.master.volume_db, set: (v) => (state.project.master.volume_db = v) });
    const note = el("p", { class: "hint", title: "Set in the Master tab" });
    const root = el(
      "div",
      { class: "strip master" },
      el("div", { class: "strip-name" }, "Master"),
      el("div", { class: "strip-body" }, meter, el("div", { class: "fader-col" }, ...volume.nodes)),
      note,
    );
    return {
      root,
      update() {
        volume.update();
        note.textContent = state.project.master.normalize ? "normalised" : "";
      },
      meter: (beat) => drawMeter(meter, levelAt(state.render?.master_peaks, beat)),
    };
  }

  return {
    root: el("div", { class: "tab-body" }, el("p", { class: "hint" }, "Meters show the rendered level at the playhead. Double-click a fader for 0 dB."), row),
    sync(reason) {
      const next = state.project.tracks.map((t) => t.id).join(",");
      if (next !== signature) {
        signature = next;
        strips = state.project.tracks.map((t, i) => trackStrip(t.id, i));
        strips.push(masterStrip());
        row.replaceChildren(...strips.map((s) => s.root));
      }
      if (reason !== "frame") for (const s of strips) s.update();
      const beat = isPlaying() ? currentBeat() : null;
      for (const s of strips) s.meter(beat);
    },
  };
}

function buildMasterTab() {
  const bind = new Bindings();
  const master = () => state.project.master;
  const p = () => state.project;
  const chain = effectChain(
    () => master().effects,
    () => (state.render?.errors ?? []).filter((e) => e.track === null),
  );
  const info = el("p", { class: "hint" });
  bind.add(() => {
    const r = state.render;
    info.textContent = r
      ? `Length ${r.length_beats} beats · ${r.duration.toFixed(1)} s, including a 3 s tail for reverb and delay.`
      : "";
  });
  const form = el(
    "div",
    { class: "track-form" },
    field("Master volume (dB)", rangeInput(bind, { get: () => master().volume_db, set: (v) => (master().volume_db = v), min: -60, max: 12, step: 0.5, format: (v) => `${v.toFixed(1)} dB` })),
    checkInput(bind, "Normalise the mix to −1 dBFS", { get: () => master().normalize, set: (v) => (master().normalize = v) }),
    el(
      "div",
      { class: "grid2" },
      field("Loop start (beat)", numberInput(bind, { get: () => p().loop_start, set: (v) => (p().loop_start = v), min: 0, max: 2048 })),
      field("Loop end (beat)", numberInput(bind, { get: () => p().loop_end, set: (v) => (p().loop_end = v), min: 0.25, max: 2048 })),
    ),
    checkInput(bind, "Loop playback (L)", { get: () => p().loop_enabled, set: (v) => (p().loop_enabled = v) }),
    info,
  );
  return {
    root: el("div", { class: "tab-body" }, el("div", { class: "split" }, form, el("div", {}, el("h3", { class: "tab-title" }, "Master effects"), chain.root))),
    sync(reason) {
      if (reason === "frame") return;
      bind.sync();
      chain.sync();
    },
  };
}

function buildPublishTab() {
  const title = el("input", { type: "text", maxlength: 200 });
  const album = el("input", { type: "text", maxlength: 200 });
  const tags = el("input", { type: "text", placeholder: "math, generative" });
  const description = el("textarea", { rows: 3, maxlength: 2000 });
  const hint = el("p", { class: "hint" });
  const message = el("p", { class: "message", role: "status" });
  const button = el("button", { class: "primary", type: "button" }, "Publish to plyr.fm");
  button.addEventListener("click", async () => {
    const r = state.render;
    if (!r?.audio) return;
    button.disabled = true;
    message.className = "message";
    message.textContent = "Uploading to plyr.fm… this can take a minute.";
    try {
      const data = await api.post("/api/publish", {
        render_id: r.audio.id,
        title: title.value.trim() || state.project.name,
        album: album.value,
        tags: tags.value,
        description: description.value,
      });
      message.className = "message ok";
      message.textContent = `Published to plyr.fm as track ${data.track_id}.`;
    } catch (error) {
      message.className = "message err";
      message.textContent = error.message;
    } finally {
      sync();
    }
  });
  function sync() {
    const s = state.status;
    const ready = s.plyrfm && s.plyr_token && Boolean(state.render?.audio);
    button.disabled = !ready;
    title.placeholder = state.project.name;
    hint.textContent = !s.plyrfm
      ? "The plyrfm package is not installed: uv pip install plyrfm==0.0.1a25"
      : !s.plyr_token
        ? "Set PLYR_TOKEN and restart mathmusic to publish. Create a token at plyr.fm/settings#developer. Your account needs an artist profile."
        : !state.render?.audio
          ? "Nothing rendered yet."
          : "Uploads the current mix as an MP3 to your plyr.fm account.";
  }
  return {
    root: el(
      "div",
      { class: "tab-body" },
      el(
        "div",
        { class: "track-form narrow" },
        hint,
        field("Title", title),
        field("Album", album),
        field("Tags", tags),
        field("Description", description),
        button,
        message,
      ),
    ),
    sync: (reason) => reason !== "frame" && sync(),
  };
}

// ---------------------------------------------------------------- wiring

export function showTab(name) {
  current = name;
  for (const [key] of TABS) {
    views[key].root.hidden = key !== name;
    $(`#tab-${key}`).setAttribute("aria-selected", String(key === name));
  }
  views[name].sync("tab");
}

export function syncPanels(reason) {
  views[current]?.sync(reason);
}

export function initPanels(nav, container) {
  views.clip = buildClipTab();
  views.track = buildTrackTab();
  views.effects = buildEffectsTab();
  views.automation = buildAutomationTab();
  views.mixer = buildMixerTab();
  views.master = buildMasterTab();
  views.publish = buildPublishTab();
  for (const [key, label] of TABS) {
    nav.append(el("button", { id: `tab-${key}`, role: "tab", type: "button", onclick: () => showTab(key) }, label));
    container.append(views[key].root);
  }
  subscribe((reason) => {
    if (reason === "focus-clip") {
      showTab("clip");
      views.clip.focus();
    }
  });
  showTab("clip");
}
