// Playback of the rendered mix: play/pause, seek in beats, and looping.

import { emit, state } from "./store.js";

const audio = new Audio();
audio.preload = "auto";
let currentUrl = null;

const secondsPerBeat = () => 60 / (state.render?.bpm || state.project?.bpm || 120);

export const isPlaying = () => !audio.paused && !audio.ended;
export const hasAudio = () => Boolean(currentUrl);
export const currentBeat = () => (audio.currentTime || 0) / secondsPerBeat();
export const currentSeconds = () => audio.currentTime || 0;

/** Swap in a new render, keeping the play position and play state. */
export function setSource(url) {
  if (url === currentUrl) return;
  const position = audio.currentTime || 0;
  const wasPlaying = isPlaying();
  currentUrl = url;
  if (!url) {
    audio.pause();
    audio.removeAttribute("src");
    audio.load();
    emit("transport");
    return;
  }
  audio.src = url;
  audio.onloadedmetadata = () => {
    audio.currentTime = Math.min(position, audio.duration || 0);
    if (wasPlaying) audio.play().catch(() => {});
    emit("transport");
  };
}

export function play() {
  if (!currentUrl) return;
  const project = state.project;
  // starting inside an enabled loop's end? jump to the loop start
  if (project.loop_enabled && currentBeat() >= project.loop_end) seekBeat(project.loop_start);
  audio.play().catch(() => {});
}

export const pause = () => audio.pause();
export const toggle = () => (isPlaying() ? pause() : play());

export function seekBeat(beat) {
  if (!currentUrl) return;
  audio.currentTime = Math.max(0, beat * secondsPerBeat());
  emit("transport");
}

/** Called every animation frame: wraps playback inside the loop region. */
export function tick() {
  const project = state.project;
  if (!project?.loop_enabled || !isPlaying()) return;
  if (currentBeat() >= project.loop_end) seekBeat(project.loop_start);
}

for (const event of ["play", "pause", "ended"]) audio.addEventListener(event, () => emit("transport"));
