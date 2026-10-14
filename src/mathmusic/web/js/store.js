// Application state, undo/redo history, rendering and autosave.
//
// Edits go through edit() (one undo step) or live()/settle() (many small
// changes, e.g. typing or dragging, that become one undo step when settled).

import { api } from "./api.js";
import { debounce, uid } from "./util.js";

const DRAFT_KEY = "mathmusic.daw.v1";
const HISTORY_LIMIT = 200;

export const state = {
  project: null,
  selection: { track: null, clip: null },
  render: null, // last successful /api/project/render response
  rendering: false,
  renderError: "",
  catalogue: { waveforms: [], instruments: [], effects: {}, scales: {}, limits: {} },
  status: {},
  dirty: false, // changed since the last save to disk
};

const listeners = new Set();
export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
export function emit(reason) {
  for (const fn of listeners) fn(reason);
}

// ---------------------------------------------------------------- lookup

export const findTrack = (id) => state.project?.tracks.find((t) => t.id === id) ?? null;

export function findClip(id) {
  for (const track of state.project?.tracks ?? []) {
    const clip = track.clips.find((c) => c.id === id);
    if (clip) return { track, clip };
  }
  return null;
}

export const selectedTrack = () => findTrack(state.selection.track);
export const selectedClip = () => findClip(state.selection.clip)?.clip ?? null;

export function select(trackId, clipId = null) {
  state.selection = { track: trackId, clip: clipId };
  emit("selection");
}

/** Render data for a clip: { samples, bounds, error } */
export function clipRender(clipId) {
  for (const track of state.render?.tracks ?? []) {
    const clip = track.clips.find((c) => c.id === clipId);
    if (clip) return clip;
  }
  return null;
}

export function errorsFor(trackId, clipId = undefined) {
  return (state.render?.errors ?? []).filter(
    (e) => e.track === trackId && (clipId === undefined || e.clip === clipId),
  );
}

// ---------------------------------------------------------------- history

const history = { past: [], future: [], pending: null };
const snapshot = () => JSON.stringify(state.project);

function begin() {
  if (history.pending === null) history.pending = snapshot();
}

/** Close the current undo step if anything changed. */
export function settle() {
  if (history.pending === null) return;
  if (history.pending !== snapshot()) {
    history.past.push(history.pending);
    if (history.past.length > HISTORY_LIMIT) history.past.shift();
    history.future = [];
  }
  history.pending = null;
  emit("history");
}

function changed() {
  state.dirty = true;
  saveDraft();
  requestRender();
  emit("project");
}

/** A discrete change: one undo step. */
export function edit(mutate) {
  settle();
  begin();
  mutate(state.project);
  changed();
  settle();
}

/** Part of a continuous change (typing, dragging). Call settle() when it ends. */
export function live(mutate) {
  begin();
  mutate(state.project);
  changed();
}

function restore(json) {
  state.project = JSON.parse(json);
  if (!findTrack(state.selection.track)) state.selection.track = state.project.tracks[0]?.id ?? null;
  if (!findClip(state.selection.clip)) state.selection.clip = null;
  changed();
  emit("selection");
}

export function undo() {
  settle();
  const previous = history.past.pop();
  if (previous === undefined) return;
  history.future.push(snapshot());
  restore(previous);
  emit("history");
}

export function redo() {
  settle();
  const next = history.future.pop();
  if (next === undefined) return;
  history.past.push(snapshot());
  restore(next);
  emit("history");
}

export const canUndo = () => history.past.length > 0 || history.pending !== null;
export const canRedo = () => history.future.length > 0;

/** Replace the whole project (new/open). Clears history. */
export function load(project, { dirty = false } = {}) {
  state.project = project;
  history.past = [];
  history.future = [];
  history.pending = null;
  state.dirty = dirty;
  state.selection = { track: project.tracks[0]?.id ?? null, clip: project.tracks[0]?.clips[0]?.id ?? null };
  saveDraft();
  requestRender(0);
  emit("project");
  emit("selection");
  emit("history");
}

// ---------------------------------------------------------------- rendering

let renderSeq = 0;
let lastRenderKey = "";

// Changes that do not affect the audio (name, loop) skip the render.
function renderKey(project) {
  const { name, loop_enabled, loop_start, loop_end, ...rest } = project;
  return JSON.stringify(rest);
}

async function renderNow() {
  const key = renderKey(state.project);
  if (key === lastRenderKey && state.render) return;
  const mine = ++renderSeq;
  state.rendering = true;
  emit("rendering");
  try {
    const data = await api.post("/api/project/render", { project: state.project });
    if (mine !== renderSeq) return;
    lastRenderKey = key;
    state.render = data;
    state.renderError = "";
  } catch (error) {
    if (mine !== renderSeq) return;
    state.renderError = error.message;
  } finally {
    if (mine === renderSeq) {
      state.rendering = false;
      emit("render");
    }
  }
}

const renderSoon = debounce(renderNow, 300);
export function requestRender(delay) {
  if (delay === 0) renderNow();
  else renderSoon();
}

// ---------------------------------------------------------------- persistence

const saveDraft = debounce(() => {
  try {
    localStorage.setItem(DRAFT_KEY, JSON.stringify({ project: state.project, dirty: state.dirty }));
  } catch {
    /* storage can be unavailable; the app works without it */
  }
}, 500);

export function loadDraft() {
  try {
    const saved = JSON.parse(localStorage.getItem(DRAFT_KEY));
    if (saved?.project?.tracks) return saved;
  } catch {
    /* ignore a corrupt draft */
  }
  return null;
}

export async function saveToDisk() {
  const name = state.project.name.trim();
  const saved = await api.put(`/api/projects/${encodeURIComponent(name)}`, { project: state.project });
  state.project.name = saved.name;
  state.dirty = false;
  saveDraft();
  emit("project");
  return saved;
}

// ---------------------------------------------------------------- factories

export function newClip(start, overrides = {}) {
  return {
    id: uid("c"),
    name: "",
    start,
    length: 8,
    expression: "sin(x)",
    x_start: 0,
    x_end: 6.283,
    notes: 16,
    rhythm: "uniform",
    invert: false,
    octave: 0,
    octaves: 2,
    y_min: null,
    y_max: null,
    gate: 0.9,
    gain: 1,
    ...overrides,
  };
}

export function newTrack(index, overrides = {}) {
  return {
    id: uid("t"),
    name: `Track ${index + 1}`,
    sound: null,
    envelope: null,
    volume_db: -6,
    pan: 0,
    mute: false,
    solo: false,
    automation: { gain: null, pan: null },
    effects: [],
    clips: [],
    ...overrides,
  };
}

export function blankProject() {
  const track = newTrack(0, { name: "Track 1", sound: "pluck" });
  track.clips.push(newClip(0, { length: 16, notes: 32, x_end: 12.566 }));
  return {
    version: 1,
    name: "Untitled",
    bpm: 110,
    root: "C4",
    scale: "pentatonic",
    loop_enabled: false,
    loop_start: 0,
    loop_end: 16,
    master: { volume_db: 0, normalize: true, effects: [] },
    tracks: [track],
  };
}
