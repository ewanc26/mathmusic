// Commands shared by buttons and keyboard shortcuts.

import { postForBlob, uploadAudio } from "./api";
import { blankProject, daw, newAudioClip, newTrack } from "./daw.svelte";
import { recorder } from "./recorder.svelte";
import { toast } from "./toast.svelte";
import { transport } from "./transport.svelte";
import type { Clip, Track } from "./types";
import { download, safeFilename, uid } from "./util";
import { view } from "./view.svelte";

export function addTrack(): void {
  const index = daw.project.tracks.length;
  const limit = daw.catalogue.limits.tracks ?? 16;
  if (index >= limit) {
    toast.show(`A project can have at most ${limit} tracks.`, "err");
    return;
  }
  const track = newTrack(index);
  daw.edit((p) => p.tracks.push(track));
  daw.select(track.id, null);
}

export function deleteClip(): void {
  const found = daw.clip(daw.selection.clip);
  if (!found) return;
  daw.edit(() => found.track.clips.splice(found.track.clips.indexOf(found.clip), 1));
  daw.select(found.track.id, null);
}

export function duplicateClip(): void {
  const found = daw.clip(daw.selection.clip);
  if (!found) return;
  const copy: Clip = { ...$state.snapshot(found.clip), id: uid("c"), start: found.clip.start + found.clip.length };
  daw.edit(() => found.track.clips.push(copy));
  daw.select(found.track.id, copy.id);
}

let clipboard: Clip | null = null;

export function copyClip(): void {
  const found = daw.clip(daw.selection.clip);
  if (!found) return;
  clipboard = $state.snapshot(found.clip) as Clip;
  toast.show("Clip copied.");
}

export function pasteClip(): void {
  const track = daw.selectedTrack ?? daw.project.tracks[0];
  if (!clipboard || !track) return;
  const selected = daw.selectedClip;
  const start = selected ? selected.start + selected.length : Math.floor(transport.beat);
  const clip: Clip = { ...structuredClone(clipboard), id: uid("c"), start };
  daw.edit(() => track.clips.push(clip));
  daw.select(track.id, clip.id);
}

/**
 * Split the selected clip at the playhead, on the snap grid. A curve clip's
 * halves keep their share of the x range and of the notes, and an automatic
 * y range is pinned to the original curve's range so pitches do not change.
 * An audio clip's second half starts further into the sample.
 */
export function splitClip(): void {
  const found = daw.clip(daw.selection.clip);
  if (!found) {
    toast.show("Select a clip to split.", "err");
    return;
  }
  const c = found.clip;
  const step = view.snap(daw.project.beats_per_bar);
  const beat = Math.round(transport.beat / step) * step;
  if (beat <= c.start + 0.01 || beat >= c.start + c.length - 0.01) {
    toast.show("Move the playhead inside the selected clip to split it.", "err");
    return;
  }
  const fraction = (beat - c.start) / c.length;
  const right: Clip = { ...$state.snapshot(c), id: uid("c"), start: beat, length: c.start + c.length - beat };
  if (c.kind === "audio") {
    right.offset = c.offset + (beat - c.start);
  } else {
    const xMid = c.x_start + fraction * (c.x_end - c.x_start);
    const leftNotes = Math.max(1, Math.round(c.notes * fraction));
    right.x_start = xMid;
    right.notes = Math.max(1, c.notes - leftNotes);
    const rendered = daw.clipRender(c.id);
    const bounds = rendered?.kind === "curve" ? rendered.bounds : undefined;
    const pin = c.y_min === null && bounds && bounds[1] > bounds[0];
    daw.edit(() => {
      if (pin) {
        [c.y_min, c.y_max] = bounds;
        [right.y_min, right.y_max] = bounds;
      }
      c.x_end = xMid;
      c.notes = leftNotes;
      c.length = beat - c.start;
      found.track.clips.push(right);
    });
    daw.select(found.track.id, right.id);
    return;
  }
  daw.edit(() => {
    c.length = beat - c.start;
    found.track.clips.push(right);
  });
  daw.select(found.track.id, right.id);
}

/** The first beat at or after `from` where a clip of `length` beats fits on the track without overlapping. */
export function firstFreeBeat(track: Track | null, from: number, length: number): number {
  let at = from;
  let moved = true;
  while (track && moved) {
    moved = false;
    for (const other of track.clips) {
      if (other.start < at + length && other.start + other.length > at) {
        at = other.start + other.length;
        moved = true;
      }
    }
  }
  return at;
}

/**
 * Import an audio file onto the selected track (or a new one), at the playhead. If the clip would
 * overlap a clip already on that track, it moves to the first free position after it.
 */
export async function importAudio(file: File): Promise<void> {
  toast.show(`Importing ${file.name}…`);
  try {
    const asset = await uploadAudio(file);
    const beats = asset.seconds / transport.secondsPerBeat;
    let track = daw.selectedTrack;
    const start = firstFreeBeat(track, Math.max(0, Math.floor(transport.beat)), beats);
    const clip = newAudioClip(start, asset.id, beats, asset.name.replace(/\.[^.]+$/, ""));
    daw.edit((p) => {
      if (!track) {
        track = newTrack(p.tracks.length, { name: clip.name || "Audio" });
        p.tracks.push(track);
      }
      track.clips.push(clip);
    });
    daw.select(track!.id, clip.id);
    toast.show(`Imported ${asset.name} (${asset.seconds.toFixed(1)} s).`, "ok");
  } catch (error) {
    toast.show(`Import failed: ${(error as Error).message}`, "err");
  }
}

export async function exportMidi(): Promise<void> {
  daw.settle();
  try {
    const blob = await postForBlob("/api/project/midi", { project: $state.snapshot(daw.project) });
    const url = URL.createObjectURL(blob);
    download(url, `${safeFilename(daw.project.name)}.mid`);
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
  } catch (error) {
    toast.show(`MIDI export failed: ${(error as Error).message}`, "err");
  }
}

export async function save(): Promise<void> {
  try {
    await daw.saveToDisk();
    toast.show(`Saved “${daw.project.name}”.`, "ok");
  } catch (error) {
    toast.show(`Not saved: ${(error as Error).message}`, "err");
  }
}

export function newProject(): void {
  if (daw.dirty && !confirm("Discard unsaved changes and start a new project?")) return;
  openProject(blankProject(), { seek: true });
}

/** Replace the project (New/Open): stop transient state so nothing leaks between songs. */
export function openProject(project: ReturnType<typeof blankProject>, { seek = false } = {}): void {
  recorder.cancel();
  clipboard = null;
  transport.pause();
  daw.load(project);
  if (seek) transport.seekBeat(0);
  view.fit(daw.songLength);
}

export function toggleLoop(): void {
  daw.edit((p) => (p.loop_enabled = !p.loop_enabled));
}
