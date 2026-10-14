// Boot and wiring: top bar, keyboard shortcuts, dialogs and the frame loop.

import { api } from "./api.js";
import { drawLanes, drawRuler, follow, initArrange, view, zoomAt, zoomToFit } from "./arrange.js";
import { TAB_ORDER, clipActions, initPanels, showTab, syncPanels } from "./panels.js";
import {
  blankProject,
  canRedo,
  canUndo,
  edit,
  findClip,
  live,
  load,
  loadDraft,
  redo,
  saveToDisk,
  select,
  selectedTrack,
  settle,
  state,
  subscribe,
  undo,
} from "./store.js";
import * as transport from "./transport.js";
import { initTracks, syncTracks } from "./tracks.js";
import { $, download, el, fmtPosition, fmtTime, isTyping, parseNote, setValue, uid } from "./util.js";

const ui = {
  name: $("#project-name"),
  dirty: $("#dirty"),
  bpm: $("#bpm"),
  root: $("#root"),
  scale: $("#scale"),
  play: $("#play"),
  loop: $("#loop"),
  position: $("#position"),
  clock: $("#clock"),
  undo: $("#undo"),
  redo: $("#redo"),
  wav: $("#export-wav"),
  mp3: $("#export-mp3"),
  status: $("#status"),
  renderState: $("#render-state"),
  snap: $("#snap"),
  toast: $("#toast"),
};

let needsDraw = true;
let lastBeat = null;

// ---------------------------------------------------------------- top bar

function toast(text, kind = "") {
  ui.toast.textContent = text;
  ui.toast.className = `toast show ${kind}`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (ui.toast.className = "toast"), 3500);
}

function syncTopBar() {
  const p = state.project;
  if (!p) return;
  setValue(ui.name, p.name);
  ui.dirty.hidden = !state.dirty;
  setValue(ui.bpm, p.bpm);
  setValue(ui.root, p.root);
  if (ui.scale.options.length !== Object.keys(state.catalogue.scales).length) {
    ui.scale.replaceChildren(...Object.keys(state.catalogue.scales).map((s) => el("option", { value: s }, s.replace("_", " "))));
  }
  setValue(ui.scale, p.scale);
  ui.loop.classList.toggle("on", p.loop_enabled);
  ui.loop.setAttribute("aria-pressed", String(p.loop_enabled));
  ui.undo.disabled = !canUndo();
  ui.redo.disabled = !canRedo();
}

function syncRender() {
  const r = state.render;
  transport.setSource(r?.audio?.url ?? null);
  const name = (state.project?.name || "mathmusic").replace(/[^A-Za-z0-9 _-]/g, "");
  for (const [link, ext] of [
    [ui.wav, "wav"],
    [ui.mp3, "mp3"],
  ]) {
    link.hidden = !r?.audio;
    if (r?.audio) {
      link.href = r.audio.url.replace(/\.wav$/, `.${ext}`);
      link.download = `${name}.${ext}`;
    }
  }
  const errors = r?.errors?.length ?? 0;
  ui.renderState.className = "render-state";
  if (state.rendering) ui.renderState.textContent = "rendering…";
  else if (state.renderError) {
    ui.renderState.textContent = `not rendered: ${state.renderError}`;
    ui.renderState.classList.add("bad");
  } else if (errors) {
    ui.renderState.textContent = `${errors} formula issue${errors === 1 ? "" : "s"} (see the highlighted clips and fields)`;
    ui.renderState.classList.add("bad");
  } else if (r) ui.renderState.textContent = `${r.duration.toFixed(1)} s rendered`;
}

function syncTransport() {
  const playing = transport.isPlaying();
  ui.play.textContent = playing ? "❚❚" : "▶";
  ui.play.setAttribute("aria-label", playing ? "Pause" : "Play");
  ui.play.disabled = !transport.hasAudio();
}

function renderStatus() {
  const pills = [
    ["MP3 export", state.status.ffmpeg],
    ["plyr.fm SDK", state.status.plyrfm],
    ["PLYR_TOKEN", state.status.plyr_token],
  ];
  ui.status.replaceChildren(
    ...pills.map(([label, ok]) => el("span", { class: `pill ${ok ? "ok" : "no"}` }, `${ok ? "✓" : "✕"} ${label}`)),
  );
}

function bindTopBar() {
  ui.name.addEventListener("input", () => live((p) => (p.name = ui.name.value)));
  ui.name.addEventListener("change", settle);

  ui.bpm.addEventListener("input", () => {
    const value = Number(ui.bpm.value);
    const ok = Number.isFinite(value) && value >= 20 && value <= 300;
    ui.bpm.classList.toggle("invalid", !ok);
    if (ok) live((p) => (p.bpm = value));
  });
  ui.bpm.addEventListener("change", () => {
    settle();
    ui.bpm.classList.remove("invalid");
    ui.bpm.value = state.project.bpm;
  });

  ui.root.addEventListener("input", () => {
    const midi = parseNote(ui.root.value);
    const ok = midi !== null && midi >= 12 && midi <= 108;
    ui.root.classList.toggle("invalid", !ok);
    if (ok) live((p) => (p.root = ui.root.value.trim()));
  });
  ui.root.addEventListener("change", () => {
    settle();
    ui.root.classList.remove("invalid");
    ui.root.value = state.project.root;
  });

  ui.scale.addEventListener("change", () => edit((p) => (p.scale = ui.scale.value)));
  ui.play.addEventListener("click", transport.toggle);
  $("#to-start").addEventListener("click", () => transport.seekBeat(state.project.loop_enabled ? state.project.loop_start : 0));
  ui.loop.addEventListener("click", toggleLoop);
  ui.undo.addEventListener("click", undo);
  ui.redo.addEventListener("click", redo);
  $("#new").addEventListener("click", newProject);
  $("#open").addEventListener("click", openDialog);
  $("#save").addEventListener("click", save);
  $("#add-track").addEventListener("click", addTrack);
  $("#zoom-in").addEventListener("click", () => zoomAt(1.4));
  $("#zoom-out").addEventListener("click", () => zoomAt(1 / 1.4));
  $("#zoom-fit").addEventListener("click", zoomToFit);
  $("#help").addEventListener("click", () => $("#help-dialog").showModal());
  $("#export-midi").addEventListener("click", exportMidi);
  ui.snap.addEventListener("change", () => (view.snap = Number(ui.snap.value)));
  view.snap = Number(ui.snap.value);
}

// ---------------------------------------------------------------- actions

function toggleLoop() {
  edit((p) => (p.loop_enabled = !p.loop_enabled));
}

function addTrack() {
  const index = state.project.tracks.length;
  if (index >= (state.catalogue.limits.tracks ?? 16)) {
    toast(`A project can have at most ${state.catalogue.limits.tracks} tracks.`, "err");
    return;
  }
  const track = {
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
  };
  edit((p) => p.tracks.push(track));
  select(track.id, null);
}

function newProject() {
  if (state.dirty && !confirm("Discard unsaved changes and start a new project?")) return;
  transport.pause();
  transport.seekBeat(0);
  load(blankProject());
  zoomToFit();
}

async function save() {
  settle();
  try {
    await saveToDisk();
    toast(`Saved “${state.project.name}”.`, "ok");
  } catch (error) {
    toast(`Not saved: ${error.message}`, "err");
  }
}

async function openDialog() {
  const dialog = $("#open-dialog");
  const list = $("#open-list");
  list.replaceChildren(el("li", { class: "hint" }, "Loading…"));
  dialog.showModal();
  try {
    const data = await api.get("/api/projects");
    $("#open-folder").textContent = data.folder;
    list.replaceChildren(
      ...(data.projects.length
        ? data.projects.map((item) =>
            el(
              "li",
              {},
              el(
                "button",
                {
                  class: "open-item",
                  type: "button",
                  onclick: async () => {
                    if (state.dirty && !confirm("Discard unsaved changes and open this project?")) return;
                    try {
                      const project = await api.get(`/api/projects/${encodeURIComponent(item.name)}`);
                      dialog.close();
                      transport.pause();
                      load(project);
                      zoomToFit();
                      toast(`Opened “${item.name}”.`, "ok");
                    } catch (error) {
                      toast(error.message, "err");
                    }
                  },
                },
                el("strong", {}, item.name),
                el("span", { class: "hint" }, new Date(item.modified).toLocaleString()),
              ),
            ),
          )
        : [el("li", { class: "hint" }, "No saved projects yet. Name your project and press Save.")]),
    );
  } catch (error) {
    list.replaceChildren(el("li", { class: "message err" }, error.message));
  }
}

async function exportMidi() {
  settle();
  try {
    const res = await fetch("/api/project/midi", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project: state.project }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => null))?.error || res.statusText);
    const url = URL.createObjectURL(await res.blob());
    const name = (state.project.name || "mathmusic").replace(/[^A-Za-z0-9 _-]/g, "");
    download(url, `${name}.mid`);
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
  } catch (error) {
    toast(`MIDI export failed: ${error.message}`, "err");
  }
}

let clipboard = null;

function copyClip() {
  const found = findClip(state.selection.clip);
  if (!found) return;
  clipboard = structuredClone(found.clip);
  toast("Clip copied.");
}

function pasteClip() {
  const track = selectedTrack() ?? state.project.tracks[0];
  if (!clipboard || !track) return;
  const selected = findClip(state.selection.clip)?.clip;
  const start = selected ? selected.start + selected.length : Math.floor(transport.currentBeat());
  const clip = { ...structuredClone(clipboard), id: uid("c"), start };
  edit(() => track.clips.push(clip));
  select(track.id, clip.id);
}

function onKey(event) {
  const mod = event.metaKey || event.ctrlKey;
  const key = event.key.toLowerCase();
  if (mod && key === "s") {
    event.preventDefault();
    save();
    return;
  }
  if (isTyping(event)) return; // let inputs keep their own shortcuts
  if (mod && key === "z") {
    event.preventDefault();
    if (event.shiftKey) redo();
    else undo();
  } else if (mod && key === "y") {
    event.preventDefault();
    redo();
  } else if (mod && key === "d") {
    event.preventDefault();
    clipActions.duplicateClip();
  } else if (mod && key === "e") {
    event.preventDefault();
    const problem = clipActions.splitClip();
    if (problem) toast(problem, "err");
  } else if (mod && key === "c") {
    copyClip();
  } else if (mod && key === "v") {
    pasteClip();
  } else if (mod) {
    return;
  } else if (event.code === "Space") {
    event.preventDefault();
    // a focused button would also "click" on key-up and toggle a second time
    if (event.target instanceof HTMLButtonElement) event.target.blur();
    transport.toggle();
  } else if (key === "backspace" || key === "delete") {
    event.preventDefault();
    clipActions.deleteClip();
  } else if (key === "home" || key === "enter") {
    transport.seekBeat(state.project.loop_enabled ? state.project.loop_start : 0);
  } else if (key === "l") {
    toggleLoop();
  } else if (key === "m" || key === "s") {
    const track = selectedTrack();
    if (track) edit(() => (track[key === "m" ? "mute" : "solo"] = !track[key === "m" ? "mute" : "solo"]));
  } else if (key === "t") {
    addTrack();
  } else if (key === "=" || key === "+") {
    zoomAt(1.4);
  } else if (key === "-") {
    zoomAt(1 / 1.4);
  } else if (key === "f") {
    zoomToFit();
  } else if (key === "?") {
    $("#help-dialog").showModal();
  } else if (/^[1-9]$/.test(key) && Number(key) <= TAB_ORDER.length) {
    showTab(TAB_ORDER[Number(key) - 1]);
  }
}

// ---------------------------------------------------------------- loop

function frame() {
  transport.tick();
  const beat = transport.hasAudio() ? transport.currentBeat() : null;
  const playing = transport.isPlaying();
  if (beat !== lastBeat) {
    if (playing && beat !== null) follow(beat);
    ui.position.textContent = fmtPosition(beat ?? 0);
    ui.clock.textContent = fmtTime(transport.currentSeconds());
    needsDraw = true;
    if (playing) syncPanels("frame");
    lastBeat = beat;
  }
  if (needsDraw) {
    drawRuler(beat);
    drawLanes(beat);
    needsDraw = false;
  }
  requestAnimationFrame(frame);
}

// ---------------------------------------------------------------- boot

subscribe((reason) => {
  if (reason === "transport") {
    syncTransport();
    needsDraw = true;
    syncPanels("frame");
    return;
  }
  if (reason === "render" || reason === "rendering") syncRender();
  if (reason === "view") {
    needsDraw = true;
    return;
  }
  syncTopBar();
  syncTracks();
  syncPanels(reason);
  needsDraw = true;
});

async function boot() {
  initArrange({ ruler: $("#ruler"), lanes: $("#lanes"), wrap: $("#lanes-wrap") });
  initTracks($("#track-headers"));
  initPanels($("#tabs"), $("#tab-bodies"));
  bindTopBar();
  document.addEventListener("keydown", onKey);
  window.addEventListener("resize", () => (needsDraw = true));
  new ResizeObserver(() => (needsDraw = true)).observe($("#lanes-wrap"));
  // keep the track headers scrolled with the lanes
  $("#lanes-wrap").addEventListener("scroll", () => ($("#track-headers").style.transform = `translateY(${-$("#lanes-wrap").scrollTop}px)`));
  window.addEventListener("beforeunload", (event) => {
    if (state.dirty) event.preventDefault();
  });

  const [catalogue, status] = await Promise.all([api.get("/api/catalogue"), api.get("/api/status")]);
  state.catalogue = catalogue;
  state.status = status;
  renderStatus();

  const draft = loadDraft();
  if (draft) load(draft.project, { dirty: draft.dirty });
  else load(await api.get("/api/project/default"));
  zoomToFit();
  syncTransport();
  requestAnimationFrame(frame);
}

boot().catch((error) => toast(`Could not start: ${error.message}`, "err"));
