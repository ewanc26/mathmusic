// Playback of the rendered mix: play/pause, seek in beats, looping, and the metronome.

import { daw } from "./daw.svelte";

/**
 * A click on every beat, higher and louder on the first beat of each bar.
 * Each click is a short sine burst with an exponential decay, synthesised
 * with Web Audio and scheduled slightly ahead against the playing audio's
 * clock. It is never part of the render or the exports.
 */
class Metronome {
  enabled = $state(false);
  private context: AudioContext | null = null;
  private nextBeat = -1;

  private ensure(): AudioContext {
    this.context ??= new AudioContext();
    return this.context;
  }

  resume(): void {
    if (this.enabled) void this.ensure().resume();
  }

  reset(): void {
    this.nextBeat = -1;
  }

  toggle(): void {
    this.enabled = !this.enabled;
    this.reset();
    this.resume();
  }

  schedule(beat: number, secondsPerBeat: number): void {
    if (!this.enabled) return;
    const context = this.ensure();
    if (this.nextBeat < 0) this.nextBeat = Math.ceil(beat - 1e-6);
    const lookahead = 0.12; // seconds
    const project = daw.project;
    const loopEnd = project.loop_enabled ? project.loop_end : Infinity;
    while ((this.nextBeat - beat) * secondsPerBeat < lookahead && this.nextBeat < loopEnd) {
      const delay = Math.max(0, (this.nextBeat - beat) * secondsPerBeat);
      this.click(context, context.currentTime + delay, this.nextBeat % project.beats_per_bar === 0);
      this.nextBeat += 1;
    }
  }

  private click(context: AudioContext, when: number, accent: boolean): void {
    const osc = context.createOscillator();
    const amp = context.createGain();
    osc.frequency.value = accent ? 1760 : 1320;
    amp.gain.setValueAtTime(accent ? 0.5 : 0.3, when);
    amp.gain.exponentialRampToValueAtTime(0.001, when + 0.06); // e^(-t/τ)
    osc.connect(amp).connect(context.destination);
    osc.start(when);
    osc.stop(when + 0.07);
  }
}

class Transport {
  playing = $state(false);
  /** Playhead position, updated every animation frame while the page is open. */
  seconds = $state(0);
  hasAudio = $state(false);
  readonly metronome = new Metronome();

  private audio: HTMLAudioElement | null = null;
  private url: string | null = null;

  readonly secondsPerBeat = $derived(60 / (daw.render?.bpm || daw.project.bpm || 120));
  readonly beat = $derived(this.seconds / this.secondsPerBeat);

  private element(): HTMLAudioElement {
    if (this.audio) return this.audio;
    const audio = new Audio();
    audio.preload = "auto";
    const sync = () => {
      this.playing = !audio.paused && !audio.ended;
      this.seconds = audio.currentTime || 0;
      this.metronome.reset();
    };
    for (const event of ["play", "pause", "ended", "seeked"]) audio.addEventListener(event, sync);
    this.audio = audio;
    return audio;
  }

  /** Swap in a new render, keeping the play position and play state. */
  setSource(url: string | null): void {
    if (url === this.url) return;
    const audio = this.element();
    const position = audio.currentTime || 0;
    const wasPlaying = this.playing;
    this.url = url;
    this.hasAudio = Boolean(url);
    this.metronome.reset();
    if (!url) {
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
      return;
    }
    audio.src = url;
    audio.onloadedmetadata = () => {
      audio.currentTime = Math.min(position, audio.duration || 0);
      if (wasPlaying) void audio.play().catch(() => {});
    };
  }

  play = (): void => {
    if (!this.url) return;
    const project = daw.project;
    if (project.loop_enabled && this.beat >= project.loop_end) this.seekBeat(project.loop_start);
    this.metronome.resume();
    void this.element()
      .play()
      .catch(() => {});
  };

  pause = (): void => this.element().pause();
  toggle = (): void => (this.playing ? this.pause() : this.play());

  seekBeat = (beat: number): void => {
    if (!this.url) return;
    const audio = this.element();
    audio.currentTime = Math.max(0, beat * this.secondsPerBeat);
    this.seconds = audio.currentTime;
    this.metronome.reset();
  };

  toStart = (): void => this.seekBeat(daw.project.loop_enabled ? daw.project.loop_start : 0);

  /** Called every animation frame: tracks the playhead, wraps loops, schedules clicks. */
  tick(): void {
    const audio = this.audio;
    if (!audio || !this.playing) return;
    this.seconds = audio.currentTime || 0;
    const project = daw.project;
    if (project.loop_enabled && this.beat >= project.loop_end) {
      this.seekBeat(project.loop_start);
      return;
    }
    this.metronome.schedule(this.beat, this.secondsPerBeat);
  }
}

export const transport = new Transport();
