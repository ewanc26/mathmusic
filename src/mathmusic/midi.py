"""Export a project's notes as a Standard MIDI File (format 1).

Track 0 carries the tempo and time signature; each DAW track becomes a MIDI
track on its own channel, with a General MIDI program chosen to resemble its
sound. Notes come from the same curve-to-note mapping the audio engine uses,
so the MIDI file matches what you hear.
"""

from __future__ import annotations

import struct

from mathmusic.engine import render_clip
from mathmusic.project import Project
from mathmusic.waves import resolve

PPQ = 480  # ticks per quarter note (one beat)

# General MIDI programs (0-based) that resemble each built-in sound
GM_PROGRAMS = {
    "sine": 79,  # ocarina
    "triangle": 73,  # flute
    "saw": 81,  # lead 2 (sawtooth)
    "square": 80,  # lead 1 (square)
    "pulse": 80,
    "organ": 16,  # drawbar organ
    "clarinet": 71,
    "brass": 61,  # brass section
    "pluck": 25,  # steel guitar
    "bell": 14,  # tubular bells
    "fm": 4,  # electric piano 1
    "hollow": 89,  # pad 2 (warm)
    "reed": 68,  # oboe
}
CHANNELS = [c for c in range(16) if c != 9]  # channel 10 is reserved for drums


def _vlq(value: int) -> bytes:
    """MIDI variable-length quantity."""
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    return bytes(reversed(out))


def _chunk(kind: bytes, body: bytes) -> bytes:
    return kind + struct.pack(">I", len(body)) + body


def _text(value: str, limit: int = 120) -> bytes:
    """UTF-8 text cut to at most `limit` bytes without splitting a character."""
    return value.encode("utf-8")[:limit].decode("utf-8", "ignore").encode("utf-8")


def _meta(kind: int, data: bytes) -> bytes:
    return bytes([0xFF, kind]) + _vlq(len(data)) + data


def _encode(events: list[tuple[int, int, bytes]]) -> bytes:
    """events: (tick, order, message). Sorted by tick; order puts note-offs before note-ons."""
    body = b""
    last = 0
    for tick, _, message in sorted(events, key=lambda e: (e[0], e[1])):
        body += _vlq(tick - last) + message
        last = tick
    return body + _vlq(0) + _meta(0x2F, b"")


def _without_overlaps(notes: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """Cut each note short when the same pitch starts again before it ends.

    A MIDI player can't tell which note-off belongs to which note-on when two
    notes of one pitch overlap, so the earlier note ends where the next begins.
    A note that would be left empty is dropped.
    """
    result: list[tuple[int, int, int, int]] = []
    last: dict[int, int] = {}  # pitch -> index in result of the note still sounding
    for on, off, pitch, velocity in sorted(notes):
        index = last.get(pitch)
        if index is not None and result[index][1] > on:
            prev_on, _, _, prev_velocity = result[index]
            if prev_on == on:
                result[index] = (-1, -1, pitch, prev_velocity)  # same start: keep only this note
            else:
                result[index] = (prev_on, on, pitch, prev_velocity)
        last[pitch] = len(result)
        result.append((on, off, pitch, velocity))
    return [note for note in result if note[0] >= 0]


def project_to_midi(project: Project) -> bytes:
    tempo = int(round(60_000_000 / project.bpm))
    conductor = [
        (0, 0, _meta(0x03, _text(project.name))),
        (0, 0, _meta(0x51, tempo.to_bytes(3, "big"))),
        (0, 0, _meta(0x58, bytes([project.beats_per_bar, 2, 24, 8]))),  # n/4
    ]
    chunks = [_chunk(b"MTrk", _encode(conductor))]

    for index, track in enumerate(project.tracks):
        channel = CHANNELS[index % len(CHANNELS)]
        try:
            name = resolve(track.sound, index).name
        except ValueError:
            name = ""
        program = GM_PROGRAMS.get(name, 0)
        events = [
            (0, 0, _meta(0x03, _text(track.name))),
            (0, 0, bytes([0xC0 | channel, program])),
        ]
        notes: list[tuple[int, int, int, int]] = []  # (on, off, pitch, velocity)
        for clip in track.clips:
            if clip.kind != "curve":
                continue  # audio clips have no notes
            try:
                result = render_clip(clip, project)
            except ValueError:
                continue  # bad formulas are reported by the audio render
            velocity = max(1, min(127, round(100 * clip.gain)))
            for step in result.steps:
                if step.pitch is None or not 0 <= step.pitch <= 127:
                    continue
                on = round(step.start * PPQ)
                off = max(on + 1, round((step.start + step.duration * clip.gate) * PPQ))
                notes.append((on, off, step.pitch, velocity))
        for on, off, pitch, velocity in _without_overlaps(notes):
            events.append((on, 1, bytes([0x90 | channel, pitch, velocity])))
            events.append((off, 0, bytes([0x80 | channel, pitch, 0])))
        chunks.append(_chunk(b"MTrk", _encode(events)))

    header = _chunk(b"MThd", struct.pack(">HHH", 1, len(chunks), PPQ))
    return header + b"".join(chunks)
