"""Waveforms and instrument presets, all defined as mathematical formulas.

A waveform is a formula in x, where x is the phase in cycles: x runs from 0
to 1 once per period, so ``sin(2*pi*x)`` is a sine. The formula is sampled
once into a wavetable, so it must be periodic over one cycle.

An instrument pairs a waveform formula with an envelope formula, also in x,
where x runs from 0 at the start of a note to 1 at its end.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from mathmusic.expr import ExpressionError, compile_expression

TABLE_SIZE = 2048
MAX_FORMULA_LENGTH = 300
DEFAULT_CYCLE = ("sine", "triangle", "saw", "square")

BUILTIN_WAVES: dict[str, str] = {
    "sine": "sin(2*pi*x)",
    "triangle": "4*abs(x-0.5)-1",
    "saw": "2*x-1",
    "square": "sign(0.5-x)",
    "pulse": "sign(0.25-x)",  # 25% duty cycle
}


def harmonics(amplitudes: dict[int, float]) -> str:
    """Additive waveform: a sum of sine partials, e.g. {1: 1, 3: 1/3} -> sin(2πx) + (1/3)·sin(6πx)."""
    return " + ".join(f"{amp:.6g}*sin(2*pi*{k}*x)" for k, amp in amplitudes.items())


@dataclass(frozen=True)
class Instrument:
    name: str
    description: str
    wave: str  # formula in x, one period
    envelope: str  # formula in x, one note


_FADE = "min(1, 20*x)*min(1, 20*(1-x))"  # 5% attack and release, so notes sit cleanly

INSTRUMENTS: dict[str, Instrument] = {
    inst.name: inst
    for inst in [
        Instrument(
            "organ",
            "Odd and even partials with falling weights, held for the whole note.",
            harmonics({1: 1, 2: 0.5, 3: 0.33, 4: 0.25, 6: 0.15}),
            _FADE,
        ),
        Instrument(
            "clarinet",
            "Odd partials only, weighted 1/k: hollow and woody.",
            harmonics({1: 1, 3: 1 / 3, 5: 1 / 5, 7: 1 / 7}),
            _FADE,
        ),
        Instrument(
            "brass",
            "Sawtooth-like Fourier series, 1/k over six partials, quick attack.",
            harmonics({k: 1 / k for k in range(1, 7)}),
            "min(1, 30*x)*min(1, 12*(1-x))",
        ),
        Instrument(
            "pluck",
            "Decaying partials that die away over the note, like a string.",
            harmonics({1: 1, 2: 0.5, 3: 0.25, 4: 0.125}),
            "exp(-6*x)",
        ),
        Instrument(
            "bell",
            "Inharmonic partials at 2.76 and 5.40 times the root, decaying: a struck bell.",
            "sin(2*pi*x) + 0.6*sin(2*pi*2.76*x) + 0.3*sin(2*pi*5.4*x)",
            "exp(-4*x)",
        ),
        Instrument(
            "fm",
            "Frequency modulation: sin(2πx + 2·sin 2πx). Glassy, with bright sidebands.",
            "sin(2*pi*x + 2*sin(2*pi*x))",
            _FADE,
        ),
        Instrument(
            "hollow",
            "Amplitude-modulated sine: a soft, breathy pad.",
            "sin(2*pi*x) * (1 + 0.5*sin(4*pi*x))",
            _FADE,
        ),
        Instrument(
            "reed",
            "Soft-clipped sine: a square-ish reed with rounded edges.",
            "tanh(4*sin(2*pi*x))",
            _FADE,
        ),
    ]
}


@dataclass(frozen=True)
class Resolved:
    name: str  # what the UI and API show: a waveform, instrument or the formula itself
    wave: str  # formula in x
    envelope: str | None  # formula in x, or None for the default click-free envelope
    instrument: str | None


def _check_formula(formula: str) -> None:
    if len(formula) > MAX_FORMULA_LENGTH:
        raise ValueError(f"formula is longer than {MAX_FORMULA_LENGTH} characters")
    compile_expression(formula)  # raises ExpressionError with a readable message


def resolve(spec: str | None, index: int = 0) -> Resolved:
    """Turn a waveform name, instrument name, or custom formula into a formula pair.

    With no spec, voices cycle through the basic waveforms by index.
    """
    if spec is None or spec == "":
        name = DEFAULT_CYCLE[index % len(DEFAULT_CYCLE)]
        return Resolved(name, BUILTIN_WAVES[name], None, None)
    if spec in INSTRUMENTS:
        inst = INSTRUMENTS[spec]
        return Resolved(inst.name, inst.wave, inst.envelope, inst.name)
    if spec in BUILTIN_WAVES:
        return Resolved(spec, BUILTIN_WAVES[spec], None, None)
    _check_formula(spec)
    wavetable(spec)  # rejects formulas that are undefined or silent over a cycle
    return Resolved(spec, spec, None, None)


def wavetable(formula: str) -> np.ndarray:
    """One period sampled on [0, 1] inclusive, normalised to a peak of 1.

    The endpoint is included, so linear interpolation wraps cleanly.
    """
    grid = np.linspace(0.0, 1.0, TABLE_SIZE + 1)
    values = compile_expression(formula).evaluate(grid)
    if not np.isfinite(values).all():
        raise ValueError(f"waveform {formula!r} is undefined somewhere in one cycle")
    peak = np.abs(values).max()
    if peak == 0:
        raise ValueError(f"waveform {formula!r} is silent")
    return values / peak


def envelope_values(formula: str | None, position: np.ndarray) -> np.ndarray:
    """Envelope gain at positions in [0, 1] across one note. None means no shaping."""
    if formula is None:
        return np.ones_like(position)
    values = compile_expression(formula).evaluate(position)
    if not np.isfinite(values).all():
        raise ExpressionError(f"envelope {formula!r} is undefined somewhere in the note")
    return values


def describe_all() -> dict:
    """Catalogue for the UI and CLI."""
    return {
        "waveforms": [{"name": name, "formula": formula} for name, formula in BUILTIN_WAVES.items()],
        "instruments": [
            {"name": inst.name, "description": inst.description, "wave": inst.wave, "envelope": inst.envelope}
            for inst in INSTRUMENTS.values()
        ],
    }
