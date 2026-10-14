// Track headers beside the lanes: name, mute/solo, volume and pan.
// Headers are keyed by track id and updated in place, so typing is never interrupted.

import { trackColor } from "./arrange.js";
import { edit, live, select, settle, state } from "./store.js";
import { el, setValue } from "./util.js";

let container;
const headers = new Map(); // track id -> { root, fields }

function findTrack(id) {
  return state.project.tracks.find((t) => t.id === id);
}

function fmtDb(db) {
  return db <= -60 ? "-∞ dB" : `${db > 0 ? "+" : ""}${db.toFixed(1)} dB`;
}

function fmtPan(pan) {
  if (Math.abs(pan) < 0.01) return "C";
  return `${pan < 0 ? "L" : "R"}${Math.round(Math.abs(pan) * 100)}`;
}

function build(id) {
  const update = (mutate) => live(() => mutate(findTrack(id)));
  const toggle = (key) => edit(() => (findTrack(id)[key] = !findTrack(id)[key]));

  const name = el("input", {
    class: "track-name",
    type: "text",
    maxlength: 80,
    spellcheck: false,
    "aria-label": "Track name",
    oninput: () => update((t) => (t.name = name.value)),
    onchange: settle,
  });
  const mute = el("button", { class: "ms mute", type: "button", title: "Mute (M)", onclick: () => toggle("mute") }, "M");
  const solo = el("button", { class: "ms solo", type: "button", title: "Solo (S)", onclick: () => toggle("solo") }, "S");
  const remove = el(
    "button",
    {
      class: "icon remove",
      type: "button",
      title: "Delete track (undo with ⌘Z)",
      onclick: () =>
        edit((p) => {
          p.tracks = p.tracks.filter((t) => t.id !== id);
          if (state.selection.track === id) state.selection = { track: p.tracks[0]?.id ?? null, clip: null };
        }),
    },
    "×",
  );

  const volume = el("input", {
    type: "range",
    min: -60,
    max: 12,
    step: 0.5,
    "aria-label": "Volume",
    title: "Volume (double-click for 0 dB)",
    oninput: () => update((t) => (t.volume_db = Number(volume.value))),
    onchange: settle,
    ondblclick: () => edit(() => (findTrack(id).volume_db = 0)),
  });
  const volumeOut = el("output", { class: "readout" });
  const pan = el("input", {
    type: "range",
    min: -1,
    max: 1,
    step: 0.05,
    "aria-label": "Pan",
    title: "Pan (double-click to centre)",
    oninput: () => update((t) => (t.pan = Number(pan.value))),
    onchange: settle,
    ondblclick: () => edit(() => (findTrack(id).pan = 0)),
  });
  const panOut = el("output", { class: "readout" });
  const sound = el("span", { class: "sound-name" });

  const root = el(
    "div",
    {
      class: "track-header",
      dataset: { id },
      onmousedown: (event) => {
        if (event.target.closest("button")) return;
        // keep the selected clip if it belongs to this track
        const clipId = findTrack(id)?.clips.some((c) => c.id === state.selection.clip) ? state.selection.clip : null;
        if (state.selection.track !== id || state.selection.clip !== clipId) select(id, clipId);
      },
    },
    el("div", { class: "row" }, el("span", { class: "swatch" }), name, mute, solo, remove),
    el("div", { class: "row small" }, el("span", { class: "label" }, "vol"), volume, volumeOut),
    el("div", { class: "row small" }, el("span", { class: "label" }, "pan"), pan, panOut, sound),
  );
  return { root, fields: { name, mute, solo, volume, volumeOut, pan, panOut, sound } };
}

export function syncTracks() {
  const project = state.project;
  if (!project) return;
  const ids = new Set(project.tracks.map((t) => t.id));
  for (const [id, header] of headers) {
    if (!ids.has(id)) {
      header.root.remove();
      headers.delete(id);
    }
  }
  const audible = new Map((state.render?.tracks ?? []).map((t) => [t.id, t]));
  project.tracks.forEach((track, index) => {
    let header = headers.get(track.id);
    if (!header) {
      header = build(track.id);
      headers.set(track.id, header);
    }
    const { root, fields } = header;
    if (container.children[index] !== root) container.insertBefore(root, container.children[index] ?? null);
    root.style.setProperty("--track-color", trackColor(index));
    root.classList.toggle("selected", track.id === state.selection.track);
    root.classList.toggle("silent", audible.get(track.id)?.audible === false);
    setValue(fields.name, track.name);
    fields.mute.classList.toggle("on", track.mute);
    fields.solo.classList.toggle("on", track.solo);
    fields.mute.setAttribute("aria-pressed", String(track.mute));
    fields.solo.setAttribute("aria-pressed", String(track.solo));
    setValue(fields.volume, track.volume_db);
    fields.volumeOut.textContent = fmtDb(track.volume_db);
    setValue(fields.pan, track.pan);
    fields.panOut.textContent = fmtPan(track.pan);
    fields.sound.textContent = audible.get(track.id)?.sound ?? track.sound ?? "";
  });
}

export function initTracks(element) {
  container = element;
}
