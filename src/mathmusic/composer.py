"""Turn sampled curves into a score.

Each expression becomes a voice. The curve is read left to right as time:
each sample becomes one step whose pitch comes from the curve's height
(normalised to the curve's own range and quantised to a scale). Samples
where the expression is undefined are rests (pitch None).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import pi

import numpy as np

from mathmusic.expr import Expression
from mathmusic.scales import pitch_table

WAVEFORMS = ("sine", "triangle", "saw", "square")


@dataclass(frozen=True)
class NoteEvent:
    start: float  # in beats
    duration: float  # in beats
    pitch: int | None  # MIDI note number, None for a rest


@dataclass
class Voice:
    expression: Expression
    x: np.ndarray
    y: np.ndarray
    waveform: str
    pan: float  # -1 (left) .. 1 (right)
    steps: list[NoteEvent] = field(default_factory=list)  # one per sample, rests included

    @property
    def notes(self) -> list[NoteEvent]:
        return [step for step in self.steps if step.pitch is not None]


@dataclass(frozen=True)
class Options:
    start: float = 0.0
    end: float = 4 * pi
    samples: int = 96
    scale: str = "pentatonic"
    root_midi: int = 60  # C4
    octaves: int = 2
    bpm: float = 120.0
    step_beats: float = 0.5
    rhythm: str = "uniform"  # "uniform" or "slope" (steep parts get shorter notes)


def _rhythm(values: np.ndarray, opts: Options) -> np.ndarray:
    if opts.rhythm == "uniform":
        return np.full(len(values), opts.step_beats)
    if opts.rhythm == "slope":
        slope = np.abs(np.gradient(values))
        peak = slope.max() if slope.size else 0.0
        steepness = slope / peak if peak > 0 else np.zeros_like(slope)
        # flat sections get full-length notes, steep sections down to a quarter of that
        return opts.step_beats * (1.0 - 0.75 * steepness)
    raise ValueError(f"unknown rhythm {opts.rhythm!r}; use 'uniform' or 'slope'")


def curve_to_steps(y: np.ndarray, opts: Options) -> list[NoteEvent]:
    """One step per sample, with pitch None where the curve is undefined."""
    pitches = pitch_table(opts.scale, opts.root_midi, opts.octaves)
    finite = np.isfinite(y)
    durations = _rhythm(np.where(finite, y, np.nan), opts)
    steps: list[NoteEvent] = []
    lo, hi = (y[finite].min(), y[finite].max()) if finite.any() else (0.0, 0.0)

    beat = 0.0
    for value, duration in zip(y, durations):
        pitch = None
        if np.isfinite(value):
            position = (value - lo) / (hi - lo) if hi > lo else 0.5
            pitch = pitches[int(round(position * (len(pitches) - 1)))]
        steps.append(NoteEvent(start=beat, duration=float(duration), pitch=pitch))
        beat += float(duration)
    return steps


def curve_to_notes(y: np.ndarray, opts: Options) -> list[NoteEvent]:
    """Only the sounding steps. NaN/inf samples are left out (rests)."""
    return [step for step in curve_to_steps(y, opts) if step.pitch is not None]


def build_voices(
    sources: list[str],
    opts: Options,
    waveforms: list[str | None] | None = None,
) -> list[Voice]:
    """Parse each expression, sample it across the domain and build its steps.

    `waveforms` optionally gives one waveform per source (None means default).
    """
    if not sources:
        raise ValueError("at least one expression is required")
    if opts.samples < 2:
        raise ValueError("samples must be at least 2")
    if opts.end <= opts.start:
        raise ValueError("end must be greater than start")
    if waveforms is not None and len(waveforms) != len(sources):
        raise ValueError("need one waveform per expression")

    x = np.linspace(opts.start, opts.end, opts.samples)
    count = len(sources)
    voices = []
    for index, source in enumerate(sources):
        expression = Expression(source)
        y = expression.evaluate(x)
        pan = 0.0 if count == 1 else -0.6 + 1.2 * index / (count - 1)
        waveform = (waveforms[index] if waveforms else None) or WAVEFORMS[index % len(WAVEFORMS)]
        if waveform not in WAVEFORMS:
            raise ValueError(f"unknown waveform {waveform!r}; choose from {', '.join(WAVEFORMS)}")
        voices.append(
            Voice(
                expression=expression,
                x=x,
                y=y,
                waveform=waveform,
                pan=pan,
                steps=curve_to_steps(y, opts),
            )
        )
    return voices
