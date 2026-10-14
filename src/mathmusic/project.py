"""Project model for the DAW.

A project is a set of tracks. Each track has a sound (waveform, instrument or
formula), mixer settings, automation formulas and an effects chain. Tracks hold
clips: each clip is a curve y = f(x) placed on the timeline, read left to right
across its length, with y mapped to pitch in the project's key.

Everything a user writes is a formula in x:
- clip expression: x runs over [x_start, x_end] across the clip
- automation: x is the position in the song, in beats
- shaper effect: x is the audio sample value

`parse_project` validates a JSON-like dict and fills defaults. It checks
structure and limits only; formulas are parsed by the engine, so one bad
formula is reported against its clip or effect without stopping the render.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from math import pi

from mathmusic.scales import SCALES, parse_note

VERSION = 1
RHYTHMS = ("uniform", "slope")
MAX_FORMULA = 300

LIMITS = {
    "tracks": 16,
    "clips_per_track": 64,
    "notes_per_clip": 1024,
    "total_notes": 8000,
    "effects": 8,
    "length_beats": 2048,
    "seconds": 600,
}

# kind, default, min, max (formula params have no range)
EFFECT_SPECS: dict[str, dict[str, tuple]] = {
    "shaper": {"formula": ("formula", "tanh(2*x)"), "mix": ("number", 1.0, 0.0, 1.0)},
    "lowpass": {"cutoff": ("number", 2000.0, 20.0, 20000.0), "q": ("number", 0.707, 0.1, 10.0)},
    "highpass": {"cutoff": ("number", 200.0, 20.0, 20000.0), "q": ("number", 0.707, 0.1, 10.0)},
    "delay": {
        "time": ("number", 0.75, 0.0625, 8.0),  # beats
        "feedback": ("number", 0.35, 0.0, 0.95),
        "mix": ("number", 0.3, 0.0, 1.0),
    },
    "reverb": {
        "size": ("number", 0.6, 0.0, 1.0),
        "damping": ("number", 0.4, 0.0, 0.99),
        "mix": ("number", 0.25, 0.0, 1.0),
    },
    "eq": {  # one parametric (peaking) band
        "freq": ("number", 1000.0, 20.0, 20000.0),
        "gain": ("number", 0.0, -24.0, 24.0),  # dB
        "q": ("number", 1.0, 0.1, 10.0),
    },
    "compressor": {
        "threshold": ("number", -18.0, -60.0, 0.0),  # dB
        "ratio": ("number", 4.0, 1.0, 20.0),
        "attack": ("number", 10.0, 0.1, 200.0),  # ms
        "release": ("number", 120.0, 5.0, 2000.0),  # ms
        "makeup": ("number", 0.0, -12.0, 24.0),  # dB
    },
}

# Number params that may instead be a formula of the beat (x = song position in beats)
AUTOMATABLE = {
    ("shaper", "mix"),
    ("lowpass", "cutoff"),
    ("lowpass", "q"),
    ("highpass", "cutoff"),
    ("highpass", "q"),
    ("delay", "feedback"),
    ("delay", "mix"),
    ("reverb", "mix"),
    ("eq", "freq"),
    ("eq", "gain"),
    ("eq", "q"),
    ("compressor", "threshold"),
}

CLIP_KINDS = ("curve", "audio")
_ID = re.compile(r"[A-Za-z0-9_-]{1,32}")
_ASSET = re.compile(r"[0-9a-f]{64}")  # sha256 of the imported audio


class ProjectError(ValueError):
    """The project dict is malformed or exceeds a limit."""


def _check_formula(formula: str, where: str) -> None:
    """Reject a formula the expression parser would refuse, at load time rather than render time."""
    from mathmusic.expr import Expression, ExpressionError

    try:
        Expression(formula)
    except ExpressionError as exc:
        raise ProjectError(f"{where}: {exc}") from None


@dataclass
class Effect:
    type: str
    params: dict[str, float | str]
    bypass: bool = False


@dataclass
class Clip:
    id: str
    start: float = 0.0  # beats
    length: float = 16.0  # beats
    expression: str = "sin(x)"
    x_start: float = 0.0
    x_end: float = 2 * pi
    notes: int = 32
    rhythm: str = "uniform"
    invert: bool = False
    octave: int = 0  # transpose from the project root
    octaves: int = 2  # pitch range
    y_min: float | None = None  # None: use the curve's own range
    y_max: float | None = None
    gate: float = 0.9  # fraction of each step that sounds
    gain: float = 1.0
    name: str = ""
    kind: str = "curve"  # "curve" plays y = f(x); "audio" plays an imported sample
    asset: str | None = None  # audio clips: id of the imported sample
    offset: float = 0.0  # audio clips: beats skipped at the start of the sample
    swing: float = 0.0  # curve clips: every second step is delayed by this fraction of a step
    fade_in: float = 0.0  # audio clips: beats
    fade_out: float = 0.0  # audio clips: beats
    fade_curve: str = "x"  # fade shape, a formula of x from 0 (silent) to 1 (full)

    @property
    def end(self) -> float:
        return self.start + self.length


@dataclass
class Send:
    bus: str  # id of a bus track
    level: float = 0.5  # 0 to 1, taken after the track's fader and effects


@dataclass
class Track:
    id: str
    name: str = "Track"
    sound: str | None = None  # waveform, instrument or formula; None cycles by index
    envelope: str | None = None  # overrides the instrument envelope
    volume_db: float = 0.0
    pan: float = 0.0
    mute: bool = False
    solo: bool = False
    gain_automation: str | None = None  # gain multiplier as a formula of the beat
    pan_automation: str | None = None  # added to pan, as a formula of the beat
    effects: list[Effect] = field(default_factory=list)
    clips: list[Clip] = field(default_factory=list)
    bus: bool = False  # an effect return: plays what other tracks send to it, holds no clips
    sends: list[Send] = field(default_factory=list)


@dataclass
class Master:
    volume_db: float = 0.0
    normalize: bool = True
    effects: list[Effect] = field(default_factory=list)


@dataclass
class Project:
    name: str = "Untitled"
    bpm: float = 110.0
    beats_per_bar: int = 4  # time signature numerator; a beat is a quarter note
    root: str = "C4"
    scale: str = "pentatonic"
    tracks: list[Track] = field(default_factory=list)
    master: Master = field(default_factory=Master)
    loop_enabled: bool = False
    loop_start: float = 0.0
    loop_end: float = 16.0
    version: int = VERSION

    @property
    def root_midi(self) -> int:
        return parse_note(self.root)

    @property
    def length_beats(self) -> float:
        ends = [clip.end for track in self.tracks for clip in track.clips]
        return max(ends, default=0.0)


# ---------------------------------------------------------------------------
# parsing helpers


def _number(raw: dict, key: str, default: float, low: float, high: float, where: str) -> float:
    value = raw.get(key, default)
    if isinstance(value, bool):
        raise ProjectError(f"{where}.{key} must be a number")
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ProjectError(f"{where}.{key} must be a number") from None
    if not math.isfinite(value) or not low <= value <= high:
        raise ProjectError(f"{where}.{key} must be between {low:g} and {high:g}")
    return value


def _integer(raw: dict, key: str, default: int, low: int, high: int, where: str) -> int:
    value = _number(raw, key, default, low, high, where)
    if value != int(value):
        raise ProjectError(f"{where}.{key} must be a whole number")
    return int(value)


def _optional_number(raw: dict, key: str, where: str) -> float | None:
    if raw.get(key) is None or raw.get(key) == "":
        return None
    return _number(raw, key, 0.0, -1e9, 1e9, where)


def _text(raw: dict, key: str, default: str, limit: int, where: str) -> str:
    value = raw.get(key, default)
    if value is None:
        value = default
    if not isinstance(value, str):
        raise ProjectError(f"{where}.{key} must be text")
    if len(value) > limit:
        raise ProjectError(f"{where}.{key} is longer than {limit} characters")
    return value


def _formula(raw: dict, key: str, where: str) -> str | None:
    value = raw.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return _text(raw, key, "", MAX_FORMULA, where).strip()


def _flag(raw: dict, key: str, default: bool, where: str) -> bool:
    value = raw.get(key, default)
    if not isinstance(value, bool):
        raise ProjectError(f"{where}.{key} must be true or false")
    return value


def _identifier(raw: dict, where: str) -> str:
    value = raw.get("id")
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ProjectError(f"{where}.id must be 1-32 letters, digits, '-' or '_'")
    return value


def _list(raw: dict, key: str, limit: int, where: str) -> list:
    value = raw.get(key) or []
    if not isinstance(value, list):
        raise ProjectError(f"{where}.{key} must be a list")
    if len(value) > limit:
        raise ProjectError(f"{where}.{key} has more than {limit} entries")
    for item in value:
        if not isinstance(item, dict):
            raise ProjectError(f"{where}.{key} entries must be objects")
    return value


def parse_effect(raw: dict, where: str) -> Effect:
    kind = raw.get("type")
    if kind not in EFFECT_SPECS:
        raise ProjectError(f"{where}.type must be one of {', '.join(EFFECT_SPECS)}")
    given = raw.get("params") or {}
    if not isinstance(given, dict):
        raise ProjectError(f"{where}.params must be an object")
    params: dict[str, float | str] = {}
    for name, spec in EFFECT_SPECS[kind].items():
        if spec[0] == "formula":
            params[name] = _formula(given, name, f"{where}.params") or spec[1]
        elif (kind, name) in AUTOMATABLE and isinstance(given.get(name), str):
            # a formula of the beat; the engine evaluates and clamps it to the param's range
            params[name] = _formula(given, name, f"{where}.params") or spec[1]
        else:
            params[name] = _number(given, name, spec[1], spec[2], spec[3], f"{where}.params")
    return Effect(type=kind, params=params, bypass=_flag(raw, "bypass", False, where))


def parse_clip(raw: dict, where: str) -> Clip:
    clip = Clip(
        id=_identifier(raw, where),
        name=_text(raw, "name", "", 80, where),
        start=_number(raw, "start", 0.0, 0.0, LIMITS["length_beats"], where),
        length=_number(raw, "length", 16.0, 0.25, LIMITS["length_beats"], where),
        expression=_text(raw, "expression", "sin(x)", MAX_FORMULA, where).strip(),
        x_start=_number(raw, "x_start", 0.0, -1e6, 1e6, where),
        x_end=_number(raw, "x_end", 2 * pi, -1e6, 1e6, where),
        notes=_integer(raw, "notes", 32, 1, LIMITS["notes_per_clip"], where),
        rhythm=_text(raw, "rhythm", "uniform", 16, where),
        invert=_flag(raw, "invert", False, where),
        octave=_integer(raw, "octave", 0, -3, 3, where),
        octaves=_integer(raw, "octaves", 2, 1, 4, where),
        y_min=_optional_number(raw, "y_min", where),
        y_max=_optional_number(raw, "y_max", where),
        gate=_number(raw, "gate", 0.9, 0.05, 1.0, where),
        gain=_number(raw, "gain", 1.0, 0.0, 2.0, where),
        kind=_text(raw, "kind", "curve", 8, where),
        offset=_number(raw, "offset", 0.0, 0.0, LIMITS["length_beats"], where),
        swing=_number(raw, "swing", 0.0, 0.0, 0.45, where),
        fade_in=_number(raw, "fade_in", 0.0, 0.0, LIMITS["length_beats"], where),
        fade_out=_number(raw, "fade_out", 0.0, 0.0, LIMITS["length_beats"], where),
        fade_curve=_formula(raw, "fade_curve", where) or "x",
    )
    _check_formula(clip.fade_curve, f"{where}.fade_curve")
    if clip.kind not in CLIP_KINDS:
        raise ProjectError(f"{where}.kind must be one of {', '.join(CLIP_KINDS)}")
    if clip.kind == "audio":
        asset = raw.get("asset")
        if not isinstance(asset, str) or not _ASSET.fullmatch(asset):
            raise ProjectError(f"{where}.asset must be the id of an imported sample")
        clip.asset = asset
    if clip.rhythm not in RHYTHMS:
        raise ProjectError(f"{where}.rhythm must be one of {', '.join(RHYTHMS)}")
    if clip.x_end <= clip.x_start:
        raise ProjectError(f"{where}.x_end must be greater than x_start")
    if (clip.y_min is None) != (clip.y_max is None):
        raise ProjectError(f"{where}: set both y_min and y_max, or neither")
    if clip.y_min is not None and clip.y_max <= clip.y_min:
        raise ProjectError(f"{where}.y_max must be greater than y_min")
    if clip.end > LIMITS["length_beats"]:
        raise ProjectError(f"{where} ends after beat {LIMITS['length_beats']}")
    return clip


def parse_track(raw: dict, where: str) -> Track:
    automation = raw.get("automation") or {}
    if not isinstance(automation, dict):
        raise ProjectError(f"{where}.automation must be an object")
    track = Track(
        id=_identifier(raw, where),
        name=_text(raw, "name", "Track", 80, where),
        sound=_formula(raw, "sound", where),
        envelope=_formula(raw, "envelope", where),
        volume_db=_number(raw, "volume_db", 0.0, -60.0, 12.0, where),
        pan=_number(raw, "pan", 0.0, -1.0, 1.0, where),
        mute=_flag(raw, "mute", False, where),
        solo=_flag(raw, "solo", False, where),
        gain_automation=_formula(automation, "gain", f"{where}.automation"),
        pan_automation=_formula(automation, "pan", f"{where}.automation"),
    )
    track.effects = [
        parse_effect(e, f"{where}.effects[{i}]") for i, e in enumerate(_list(raw, "effects", LIMITS["effects"], where))
    ]
    track.clips = [
        parse_clip(c, f"{where}.clips[{i}]") for i, c in enumerate(_list(raw, "clips", LIMITS["clips_per_track"], where))
    ]
    track.bus = _flag(raw, "bus", False, where)
    track.sends = []
    for i, send in enumerate(_list(raw, "sends", LIMITS["tracks"], where)):
        bus = send.get("bus")
        if not isinstance(bus, str) or not _ID.fullmatch(bus):
            raise ProjectError(f"{where}.sends[{i}].bus must be a track id")
        track.sends.append(Send(bus=bus, level=_number(send, "level", 0.5, 0.0, 1.0, f"{where}.sends[{i}]")))
    if track.bus and track.clips:
        raise ProjectError(f"{where} is a bus; buses hold no clips")
    if track.bus and track.sends:
        raise ProjectError(f"{where} is a bus; buses cannot send (that could feed back)")
    return track


def parse_project(raw: dict) -> Project:
    if not isinstance(raw, dict):
        raise ProjectError("project must be an object")
    version = raw.get("version", VERSION)
    if version != VERSION:
        raise ProjectError(f"unsupported project version {version!r}; this build reads version {VERSION}")
    master_raw = raw.get("master") or {}
    if not isinstance(master_raw, dict):
        raise ProjectError("master must be an object")

    project = Project(
        name=_text(raw, "name", "Untitled", 80, "project") or "Untitled",
        bpm=_number(raw, "bpm", 110.0, 20.0, 300.0, "project"),
        beats_per_bar=_integer(raw, "beats_per_bar", 4, 1, 16, "project"),
        root=_text(raw, "root", "C4", 4, "project"),
        scale=_text(raw, "scale", "pentatonic", 32, "project"),
        loop_enabled=_flag(raw, "loop_enabled", False, "project"),
        loop_start=_number(raw, "loop_start", 0.0, 0.0, LIMITS["length_beats"], "project"),
        loop_end=_number(raw, "loop_end", 16.0, 0.0, LIMITS["length_beats"], "project"),
        master=Master(
            volume_db=_number(master_raw, "volume_db", 0.0, -60.0, 12.0, "master"),
            normalize=_flag(master_raw, "normalize", True, "master"),
            effects=[
                parse_effect(e, f"master.effects[{i}]")
                for i, e in enumerate(_list(master_raw, "effects", LIMITS["effects"], "master"))
            ],
        ),
    )
    try:
        parse_note(project.root)
    except ValueError as exc:
        raise ProjectError(str(exc)) from None
    if project.scale not in SCALES:
        raise ProjectError(f"project.scale must be one of {', '.join(SCALES)}")
    if project.loop_end <= project.loop_start:
        raise ProjectError("project.loop_end must be greater than loop_start")

    project.tracks = [
        parse_track(t, f"tracks[{i}]") for i, t in enumerate(_list(raw, "tracks", LIMITS["tracks"], "project"))
    ]
    ids = [t.id for t in project.tracks] + [c.id for t in project.tracks for c in t.clips]
    if len(ids) != len(set(ids)):
        raise ProjectError("track and clip ids must be unique")
    buses = {t.id for t in project.tracks if t.bus}
    for index, track in enumerate(project.tracks):
        targets = [send.bus for send in track.sends]
        if len(targets) != len(set(targets)):
            raise ProjectError(f"tracks[{index}] sends to the same bus twice")
        for send in track.sends:
            if send.bus not in buses:
                raise ProjectError(f"tracks[{index}] sends to {send.bus!r}, which is not a bus track")
    total_notes = sum(c.notes for t in project.tracks for c in t.clips if c.kind == "curve")
    if total_notes > LIMITS["total_notes"]:
        raise ProjectError(f"the project has {total_notes} notes; the limit is {LIMITS['total_notes']}")
    if project.length_beats * 60.0 / project.bpm > LIMITS["seconds"]:
        raise ProjectError(f"the project is longer than {LIMITS['seconds'] // 60} minutes")
    return project


# ---------------------------------------------------------------------------
# serialising


def effect_to_dict(effect: Effect) -> dict:
    return {"type": effect.type, "bypass": effect.bypass, "params": dict(effect.params)}


def clip_to_dict(clip: Clip) -> dict:
    return {
        "id": clip.id,
        "name": clip.name,
        "start": clip.start,
        "length": clip.length,
        "expression": clip.expression,
        "x_start": clip.x_start,
        "x_end": clip.x_end,
        "notes": clip.notes,
        "rhythm": clip.rhythm,
        "invert": clip.invert,
        "octave": clip.octave,
        "octaves": clip.octaves,
        "y_min": clip.y_min,
        "y_max": clip.y_max,
        "gate": clip.gate,
        "gain": clip.gain,
        "kind": clip.kind,
        "asset": clip.asset,
        "offset": clip.offset,
        "swing": clip.swing,
        "fade_in": clip.fade_in,
        "fade_out": clip.fade_out,
        "fade_curve": clip.fade_curve,
    }


def track_to_dict(track: Track) -> dict:
    return {
        "id": track.id,
        "name": track.name,
        "sound": track.sound,
        "envelope": track.envelope,
        "volume_db": track.volume_db,
        "pan": track.pan,
        "mute": track.mute,
        "solo": track.solo,
        "automation": {"gain": track.gain_automation, "pan": track.pan_automation},
        "effects": [effect_to_dict(e) for e in track.effects],
        "clips": [clip_to_dict(c) for c in track.clips],
        "bus": track.bus,
        "sends": [{"bus": send.bus, "level": send.level} for send in track.sends],
    }


def project_to_dict(project: Project) -> dict:
    return {
        "version": project.version,
        "name": project.name,
        "bpm": project.bpm,
        "beats_per_bar": project.beats_per_bar,
        "root": project.root,
        "scale": project.scale,
        "loop_enabled": project.loop_enabled,
        "loop_start": project.loop_start,
        "loop_end": project.loop_end,
        "master": {
            "volume_db": project.master.volume_db,
            "normalize": project.master.normalize,
            "effects": [effect_to_dict(e) for e in project.master.effects],
        },
        "tracks": [track_to_dict(t) for t in project.tracks],
    }


def default_project() -> Project:
    """A small starting arrangement: three tracks, one curve each."""
    return parse_project(
        {
            "name": "Untitled",
            "bpm": 110,
            "root": "C4",
            "scale": "pentatonic",
            "loop_end": 32,
            "master": {"effects": [{"type": "reverb", "params": {"size": 0.5, "mix": 0.15}}]},
            "tracks": [
                {
                    "id": "t1",
                    "name": "Sine",
                    "sound": "pluck",
                    "volume_db": -3,
                    "pan": -0.4,
                    "clips": [
                        {"id": "c1", "start": 0, "length": 16, "expression": "sin(x)", "x_end": 4 * pi, "notes": 32},
                        {"id": "c4", "start": 16, "length": 16, "expression": "sin(x)*cos(x/3)", "x_end": 4 * pi, "notes": 32},
                    ],
                },
                {
                    "id": "t2",
                    "name": "Rise",
                    "sound": "organ",
                    "volume_db": -9,
                    "effects": [{"type": "lowpass", "params": {"cutoff": 1800}}],
                    "clips": [
                        {"id": "c2", "start": 0, "length": 32, "expression": "x^2", "x_end": 4, "notes": 16, "octave": -1},
                    ],
                },
                {
                    "id": "t3",
                    "name": "Bells",
                    "sound": "bell",
                    "volume_db": -6,
                    "pan": 0.4,
                    "effects": [{"type": "delay", "params": {"time": 0.75, "feedback": 0.35, "mix": 0.25}}],
                    "clips": [
                        {"id": "c3", "start": 8, "length": 24, "expression": "2*sinc(x-4)", "x_end": 12, "notes": 24, "octave": 1},
                    ],
                },
            ],
        }
    )
