"""Turn sampled curves into a score.

Each expression becomes a voice. The curve is read left to right as time:
each sample becomes one step whose pitch comes from the curve's height,
quantised to a scale. Samples where the expression is undefined are rests
(pitch None).

Pitch range: by default ("shared") every voice is mapped onto one range set
by the lowest and highest value across all voices, so relative height and
amplitude are preserved. "per-voice" stretches each curve to fill the range,
which makes its shape clearer but hides differences in amplitude.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import pi

import numpy as np

from mathmusic.expr import Expression
from mathmusic.scales import pitch_table

WAVEFORMS = ("sine", "triangle", "saw", "square")
PITCH_MODES = ("shared", "per-voice")


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
    inverted: bool = False  # high values sound low (polarity)
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
    pitch_mode: str = "shared"  # "shared" or "per-voice"


def _steepness(values: np.ndarray) -> np.ndarray:
    """0 on flat sections, up to 1 on steep ones, relative to the curve's own average slope.

    Undefined samples are bridged by interpolation, so a rest does not flatten
    the rhythm around it. A straight line gets a steady mid value rather than
    all-steep notes.
    """
    finite = np.isfinite(values)
    if finite.sum() < 2:
        return np.zeros(len(values))
    index = np.arange(len(values))
    filled = np.interp(index, index[finite], values[finite])
    slope = np.abs(np.gradient(filled))
    average = slope.mean()
    if average <= 0:
        return np.zeros(len(values))
    return np.clip(slope / (2 * average), 0.0, 1.0)


def _rhythm(values: np.ndarray, opts: Options) -> np.ndarray:
    if opts.rhythm == "uniform":
        return np.full(len(values), opts.step_beats)
    if opts.rhythm == "slope":
        # flat sections get full-length notes, steep sections down to a quarter of that
        return opts.step_beats * (1.0 - 0.75 * _steepness(values))
    raise ValueError(f"unknown rhythm {opts.rhythm!r}; use 'uniform' or 'slope'")


def value_bounds(ys: list[np.ndarray]) -> tuple[float, float]:
    """Lowest and highest finite value across several curves, or (0, 0) if there are none."""
    finite = [y[np.isfinite(y)] for y in ys]
    finite = [f for f in finite if f.size]
    if not finite:
        return 0.0, 0.0
    return float(min(f.min() for f in finite)), float(max(f.max() for f in finite))


def curve_to_steps(
    y: np.ndarray,
    opts: Options,
    bounds: tuple[float, float] | None = None,
    invert: bool = False,
) -> list[NoteEvent]:
    """One step per sample, with pitch None where the curve is undefined.

    `bounds` gives the value range that maps onto the full pitch range. When it
    is None the curve's own range is used.
    """
    pitches = pitch_table(opts.scale, opts.root_midi, opts.octaves)
    finite = np.isfinite(y)
    durations = _rhythm(np.where(finite, y, np.nan), opts)
    lo, hi = bounds if bounds is not None else value_bounds([y])
    steps: list[NoteEvent] = []

    beat = 0.0
    for value, duration in zip(y, durations):
        pitch = None
        if np.isfinite(value):
            position = (value - lo) / (hi - lo) if hi > lo else 0.5
            position = min(max(position, 0.0), 1.0)
            if invert:
                position = 1.0 - position
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
    inverts: list[bool] | None = None,
) -> list[Voice]:
    """Parse each expression, sample it across the domain and build its steps.

    `waveforms` and `inverts` optionally give one value per source.
    """
    if not sources:
        raise ValueError("at least one expression is required")
    if opts.samples < 2:
        raise ValueError("samples must be at least 2")
    if opts.end <= opts.start:
        raise ValueError("end must be greater than start")
    if opts.pitch_mode not in PITCH_MODES:
        raise ValueError(f"unknown pitch mode {opts.pitch_mode!r}; use 'shared' or 'per-voice'")
    if waveforms is not None and len(waveforms) != len(sources):
        raise ValueError("need one waveform per expression")
    if inverts is not None and len(inverts) != len(sources):
        raise ValueError("need one invert flag per expression")

    x = np.linspace(opts.start, opts.end, opts.samples)
    count = len(sources)
    expressions = [Expression(source) for source in sources]
    curves = [expression.evaluate(x) for expression in expressions]
    shared = value_bounds(curves) if opts.pitch_mode == "shared" else None

    voices = []
    for index, (expression, y) in enumerate(zip(expressions, curves)):
        pan = 0.0 if count == 1 else -0.6 + 1.2 * index / (count - 1)
        waveform = (waveforms[index] if waveforms else None) or WAVEFORMS[index % len(WAVEFORMS)]
        if waveform not in WAVEFORMS:
            raise ValueError(f"unknown waveform {waveform!r}; choose from {', '.join(WAVEFORMS)}")
        invert = bool(inverts[index]) if inverts else False
        voices.append(
            Voice(
                expression=expression,
                x=x,
                y=y,
                waveform=waveform,
                pan=pan,
                inverted=invert,
                steps=curve_to_steps(y, opts, bounds=shared, invert=invert),
            )
        )
    return voices
