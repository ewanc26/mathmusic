// Application state (Svelte 5 runes), undo/redo, rendering and autosave.
//
// Edits go through edit() (one undo step) or live()/settle() (many small
// changes, e.g. typing or dragging, that become one undo step when settled).
// Components never mutate the project outside these, so every change can be undone.

import { api } from "./api";
import type { Catalogue, Clip, ClipRender, Project, RenderError, RenderResponse, Status, Track } from "./types";
import { debounce, uid } from "./util";

const DRAFT_KEY = "mathmusic.daw.v1";
const HISTORY_LIMIT = 200;

// ---------------------------------------------------------------- factories

export function newClip(start: number, overrides: Partial<Clip> = {}): Clip {
  return {
    id: uid("c"),
    name: "",
    kind: "curve",
    start,
    length: 8,
    gain: 1,
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
    asset: null,
    offset: 0,
    fade_in: 0,
    fade_out: 0,
    fade_curve: "x",
    swing: 0,
    ...overrides,
  };
}

export function newAudioClip(start: number, asset: string, lengthBeats: number, name: string): Clip {
  return newClip(start, { kind: "audio", asset, name, length: Math.max(0.25, Math.round(lengthBeats * 4) / 4) });
}

export function newTrack(index: number, overrides: Partial<Track> = {}): Track {
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
    bus: false,
    sends: [],
    ...overrides,
  };
}

export function blankProject(): Project {
  const track = newTrack(0, { name: "Track 1", sound: "pluck" });
  track.clips.push(newClip(0, { length: 16, notes: 32, x_end: 12.566 }));
  return {
    version: 1,
    name: "Untitled",
    bpm: 110,
    beats_per_bar: 4,
    root: "C4",
    scale: "pentatonic",
    loop_enabled: false,
    loop_start: 0,
    loop_end: 16,
    master: { volume_db: 0, normalize: true, effects: [] },
    tracks: [track],
  };
}

/** Fill fields that older saved projects or drafts may lack. */
function upgrade(project: Project): Project {
  project.beats_per_bar ??= 4;
  for (const track of project.tracks) {
    track.automation ??= { gain: null, pan: null };
    track.bus ??= false;
    track.sends ??= [];
    for (const clip of track.clips) {
      clip.kind ??= "curve";
      clip.asset ??= null;
      clip.offset ??= 0;
      clip.fade_in ??= 0;
      clip.fade_out ??= 0;
      clip.fade_curve ??= "x";
      clip.swing ??= 0;
    }
  }
  return project;
}

// Changes that do not affect the audio (name, loop, time signature) skip the render.
function renderKey(project: Project): string {
  const { name: _n, loop_enabled: _e, loop_start: _s, loop_end: _l, beats_per_bar: _b, ...audible } = project;
  return JSON.stringify(audible);
}

// ---------------------------------------------------------------- state

class Daw {
  project = $state<Project>(blankProject());
  selection = $state<{ track: string | null; clip: string | null }>({ track: null, clip: null });
  render = $state.raw<RenderResponse | null>(null);
  rendering = $state(false);
  renderError = $state("");
  catalogue = $state.raw<Catalogue>({ waveforms: [], instruments: [], effects: {}, scales: {}, limits: {} });
  status = $state.raw<Status>({});
  dirty = $state(false);
  ready = $state(false);

  private past: string[] = [];
  private future: string[] = [];
  private pending: string | null = null;
  private historySize = $state(0); // reactive mirror so undo/redo buttons update

  readonly canUndo = $derived(this.historySize >= 0 && (this.past.length > 0 || this.pending !== null));
  readonly canRedo = $derived(this.historySize >= 0 && this.future.length > 0);

  // -------------------------------------------------------------- lookup

  track(id: string | null): Track | null {
    return this.project.tracks.find((t) => t.id === id) ?? null;
  }

  clip(id: string | null): { track: Track; clip: Clip } | null {
    for (const track of this.project.tracks) {
      const clip = track.clips.find((c) => c.id === id);
      if (clip) return { track, clip };
    }
    return null;
  }

  get selectedTrack(): Track | null {
    return this.track(this.selection.track);
  }

  get selectedClip(): Clip | null {
    return this.clip(this.selection.clip)?.clip ?? null;
  }

  select(trackId: string | null, clipId: string | null = null): void {
    this.selection = { track: trackId, clip: clipId };
  }

  clipRender(clipId: string | null | undefined): ClipRender | null {
    for (const track of this.render?.tracks ?? []) {
      const clip = track.clips.find((c) => c.id === clipId);
      if (clip) return clip;
    }
    return null;
  }

  trackRender(trackId: string) {
    return this.render?.tracks.find((t) => t.id === trackId) ?? null;
  }

  /** Render errors for a track; pass clipId to narrow to one clip (null for track-level errors). */
  errorsFor(trackId: string | null | undefined, clipId?: string | null): RenderError[] {
    return (this.render?.errors ?? []).filter(
      (e) => e.track === trackId && (clipId === undefined || e.clip === clipId),
    );
  }

  get songLength(): number {
    return Math.max(16, ...this.project.tracks.flatMap((t) => t.clips.map((c) => c.start + c.length)));
  }

  // -------------------------------------------------------------- history

  private snapshot(): string {
    return JSON.stringify($state.snapshot(this.project));
  }

  private begin(): void {
    if (this.pending === null) this.pending = this.snapshot();
  }

  private bumpHistory(): void {
    this.historySize++;
  }

  /** Close the current undo step if anything changed. */
  settle = (): void => {
    if (this.pending === null) return;
    if (this.pending !== this.snapshot()) {
      this.past.push(this.pending);
      if (this.past.length > HISTORY_LIMIT) this.past.shift();
      this.future = [];
    }
    this.pending = null;
    this.bumpHistory();
  };

  private changed(): void {
    this.dirty = true;
    this.saveDraft();
    this.requestRender();
    this.bumpHistory();
  }

  /** A discrete change: one undo step. */
  edit = (mutate: (project: Project) => void): void => {
    this.settle();
    this.begin();
    mutate(this.project);
    this.changed();
    this.settle();
  };

  /** Part of a continuous change (typing, dragging). Call settle() when it ends. */
  live = (mutate: (project: Project) => void): void => {
    this.begin();
    mutate(this.project);
    this.changed();
  };

  private restore(json: string): void {
    this.project = JSON.parse(json) as Project;
    if (!this.track(this.selection.track)) this.selection.track = this.project.tracks[0]?.id ?? null;
    if (!this.clip(this.selection.clip)) this.selection.clip = null;
    this.changed();
  }

  undo = (): void => {
    this.settle();
    const previous = this.past.pop();
    if (previous === undefined) return;
    this.future.push(this.snapshot());
    this.restore(previous);
  };

  redo = (): void => {
    this.settle();
    const next = this.future.pop();
    if (next === undefined) return;
    this.past.push(this.snapshot());
    this.restore(next);
  };

  /** Replace the whole project (new/open). Clears history. */
  load(project: Project, { dirty = false } = {}): void {
    this.project = upgrade(project);
    this.past = [];
    this.future = [];
    this.pending = null;
    this.dirty = dirty;
    const first = this.project.tracks[0];
    this.selection = { track: first?.id ?? null, clip: first?.clips[0]?.id ?? null };
    this.saveDraft();
    this.requestRender(0);
    this.bumpHistory();
  }

  // -------------------------------------------------------------- rendering

  private renderSeq = 0;
  private lastRenderKey = "";

  private async renderNow(): Promise<void> {
    const key = renderKey($state.snapshot(this.project));
    if (key === this.lastRenderKey && this.render) return;
    const mine = ++this.renderSeq;
    this.rendering = true;
    try {
      const data = await api.post<RenderResponse>("/api/project/render", { project: $state.snapshot(this.project) });
      if (mine !== this.renderSeq) return;
      this.lastRenderKey = key;
      this.render = data;
      this.renderError = "";
    } catch (error) {
      if (mine !== this.renderSeq) return;
      this.renderError = (error as Error).message;
    } finally {
      if (mine === this.renderSeq) this.rendering = false;
    }
  }

  private renderSoon = debounce(() => void this.renderNow(), 300);

  requestRender(delay?: number): void {
    if (delay === 0) void this.renderNow();
    else this.renderSoon();
  }

  // -------------------------------------------------------------- persistence

  private saveDraft = debounce(() => {
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify({ project: $state.snapshot(this.project), dirty: this.dirty }));
    } catch {
      /* storage can be unavailable; the app works without it */
    }
  }, 500);

  loadDraft(): { project: Project; dirty: boolean } | null {
    try {
      const saved = JSON.parse(localStorage.getItem(DRAFT_KEY) ?? "null") as {
        project?: Project;
        dirty?: boolean;
      } | null;
      if (saved?.project?.tracks) return { project: saved.project, dirty: Boolean(saved.dirty) };
    } catch {
      /* ignore a corrupt draft */
    }
    return null;
  }

  async saveToDisk(): Promise<void> {
    this.settle();
    const name = this.project.name.trim();
    const saved = await api.put<Project>(`/api/projects/${encodeURIComponent(name)}`, {
      project: $state.snapshot(this.project),
    });
    this.project.name = saved.name;
    this.dirty = false;
    this.saveDraft();
  }
}

export const daw = new Daw();
