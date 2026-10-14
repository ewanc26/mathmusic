"""Scales and pitch tables used to quantise curve values into notes."""

from __future__ import annotations

import re

SCALES: dict[str, list[int]] = {
    "major": [0, 2, 4, 5, 7, 9, 11],
    "minor": [0, 2, 3, 5, 7, 8, 10],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "pentatonic": [0, 2, 4, 7, 9],
    "minor_pentatonic": [0, 3, 5, 7, 10],
    "whole_tone": [0, 2, 4, 6, 8, 10],
    "chromatic": list(range(12)),
}


_NOTE_OFFSETS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_ACCIDENTALS = {"": 0, "#": 1, "b": -1}


def parse_note(name: str) -> int:
    """MIDI number for a note name such as C4, F#3 or Bb2 (C4 = 60)."""
    match = re.fullmatch(r"([A-Ga-g])([#b]?)(-?\d+)", name.strip())
    if not match:
        raise ValueError(f"bad note name {name!r}; use something like C4 or F#3")
    letter, accidental, octave = match.groups()
    semitone = _NOTE_OFFSETS[letter.upper()] + _ACCIDENTALS[accidental]
    return 12 * (int(octave) + 1) + semitone


def pitch_table(scale: str, root_midi: int, octaves: int) -> list[int]:
    """MIDI note numbers for `octaves` octaves of `scale` above `root_midi`, plus the top tonic."""
    if scale not in SCALES:
        raise ValueError(f"unknown scale {scale!r}; choose from {', '.join(SCALES)}")
    if octaves < 1:
        raise ValueError("octaves must be at least 1")
    degrees = SCALES[scale]
    pitches = [root_midi + 12 * octave + d for octave in range(octaves) for d in degrees]
    pitches.append(root_midi + 12 * octaves)
    return pitches
