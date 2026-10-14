"""Render a project: clips -> notes -> track audio -> effects -> master mix.

Formula errors are collected rather than raised: a clip, sound, automation
or effect with a bad formula is skipped and reported, and the rest of the
project still renders.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from dataclasses import dataclass, field

import numpy as np

from mathmusic import dsp
from mathmusic.composer import NoteEvent, Options, curve_to_steps, value_bounds
from mathmusic.expr import Expression
from mathmusic.assets import load_asset
from mathmusic.project import EFFECT_SPECS, Clip, Project, Track, track_to_dict
from mathmusic.synth import PEAK, SAMPLE_RATE, add_notes
from mathmusic.waves import envelope_values, resolve, wavetable

TAIL_SECONDS = 3.0  # room for release, delay and reverb tails after the last note
CONTROL_STEP = 64  # automation is evaluated every 64 samples and interpolated
CACHE_BYTES = 400 * 1024 * 1024
PEAKS_PER_BEAT = 16  # resolution of the level data sent to the UI for waveforms and meters


def peaks(stereo: np.ndarray | None, samples_per_bucket: int, scale: float = 1.0) -> list[float]:
    """Peak level per bucket (max |sample| over both channels), for drawing waveforms and meters."""
    if stereo is None or not len(stereo):
        return []
    step = max(1, samples_per_bucket)
    level = np.abs(stereo).max(axis=1) * scale
    count = int(np.ceil(len(level) / step))
    level = np.pad(level, (0, count * step - len(level)))
    return np.round(level.reshape(count, step).max(axis=1), 4).tolist()


def db_to_gain(db: float) -> float:
    return float(10 ** (db / 20))


@dataclass
class ClipRender:
    clip: Clip
    x: np.ndarray
    y: np.ndarray
    steps: list[NoteEvent]  # absolute beats, rests included
    bounds: tuple[float, float]


def render_clip(clip: Clip, project: Project) -> ClipRender:
    """Sample the clip's curve and turn it into steps placed on the timeline."""
    x = np.linspace(clip.x_start, clip.x_end, clip.notes)
    y = Expression(clip.expression).evaluate(x)
    opts = Options(
        start=clip.x_start,
        end=clip.x_end,
        samples=clip.notes,
        scale=project.scale,
        root_midi=project.root_midi + 12 * clip.octave,
        octaves=clip.octaves,
        bpm=project.bpm,
        step_beats=clip.length / clip.notes,
        rhythm=clip.rhythm,
    )
    fixed = (clip.y_min, clip.y_max) if clip.y_min is not None else None
    local = curve_to_steps(y, opts, bounds=fixed, invert=clip.invert)
    # slope rhythm shortens steps; stretch them so the clip fills its length
    total = sum(step.duration for step in local)
    stretch = clip.length / total if total > 0 else 1.0
    steps = [
        NoteEvent(start=clip.start + step.start * stretch, duration=step.duration * stretch, pitch=step.pitch)
        for step in local
    ]
    return ClipRender(clip=clip, x=x, y=y, steps=steps, bounds=fixed or value_bounds([y]))


def _automation(formula: str, beats: np.ndarray) -> np.ndarray:
    """Evaluate a formula of the beat at control rate and interpolate to every sample."""
    coarse = beats[::CONTROL_STEP]
    values = Expression(formula).evaluate(coarse)
    if not np.isfinite(values).all():
        raise ValueError(f"automation {formula!r} is undefined somewhere in the song")
    return np.interp(beats, coarse, values)


def _resolve_params(effect, beats: np.ndarray) -> dict:
    """Effect params with any formula of the beat turned into a per-sample curve, clamped to range."""
    params = {}
    for name, value in effect.params.items():
        spec = EFFECT_SPECS[effect.type][name]
        if spec[0] == "number" and isinstance(value, str):
            params[name] = np.clip(_automation(value, beats), spec[2], spec[3])
        else:
            params[name] = value
    return params


def apply_chain(stereo, effects, where: dict, errors: list, seconds_per_beat: float, sample_rate: int, beats: np.ndarray):
    for index, effect in enumerate(effects):
        if effect.bypass:
            continue
        try:
            params = _resolve_params(effect, beats)
            stereo = dsp.apply_effect(stereo, effect.type, params, sample_rate, seconds_per_beat)
        except ValueError as exc:
            errors.append({**where, "field": f"effects[{index}]", "error": str(exc)})
    return stereo


@dataclass
class TrackRender:
    stereo: np.ndarray | None  # None when the track is silent (muted, not soloed, or empty)
    clips: list[dict]
    errors: list[dict]


def _curve_clip_data(result: ClipRender) -> dict:
    return {
        "id": result.clip.id,
        "kind": "curve",
        "bounds": list(result.bounds),
        "samples": [
            {
                "x": float(xv),
                "y": float(yv) if np.isfinite(yv) else None,
                "start": step.start,
                "duration": step.duration,
                "pitch": step.pitch,
            }
            for xv, yv, step in zip(result.x, result.y, result.steps)
        ],
    }


def _render_track(track: Track, index: int, project: Project, total: int, audible: bool, sample_rate: int) -> TrackRender:
    spb = 60.0 / project.bpm
    bucket = int(round(spb * sample_rate / PEAKS_PER_BEAT))
    errors: list[dict] = []
    where = {"track": track.id, "clip": None}

    clip_data: list[dict] = []
    curves: list[ClipRender] = []
    samples: list[tuple[int, np.ndarray, float]] = []  # (start sample, audio, gain)
    for clip in track.clips:
        if clip.kind == "audio":
            try:
                audio = load_asset(clip.asset)
            except ValueError as exc:
                errors.append({"track": track.id, "clip": clip.id, "field": "asset", "error": str(exc)})
                clip_data.append({"id": clip.id, "kind": "audio", "peaks": [], "error": str(exc)})
                continue
            offset = int(round(clip.offset * spb * sample_rate))
            length = int(round(clip.length * spb * sample_rate))
            segment = audio[offset : offset + length]
            samples.append((int(round(clip.start * spb * sample_rate)), segment, clip.gain))
            clip_data.append(
                {
                    "id": clip.id,
                    "kind": "audio",
                    "seconds": len(audio) / sample_rate,
                    "peaks": peaks(segment, bucket),
                }
            )
            continue
        try:
            result = render_clip(clip, project)
        except ValueError as exc:
            errors.append({"track": track.id, "clip": clip.id, "field": "expression", "error": str(exc)})
            clip_data.append({"id": clip.id, "kind": "curve", "samples": [], "error": str(exc)})
            continue
        curves.append(result)
        clip_data.append(_curve_clip_data(result))

    sound = envelope = None
    if curves:
        try:
            sound = resolve(track.sound, index)
            envelope = track.envelope or sound.envelope
            if envelope is not None:
                envelope_values(envelope, np.linspace(0, 1, 16))
            wavetable(sound.wave)
        except ValueError as exc:
            errors.append({**where, "field": "sound", "error": str(exc)})
            sound = None  # curve clips fall silent; audio clips still play

    if not audible or not (samples or (curves and sound)):
        return TrackRender(stereo=None, clips=clip_data, errors=errors)

    mono = np.zeros(total)
    if sound is not None:
        for result in curves:
            notes = [step for step in result.steps if step.pitch is not None]
            add_notes(mono, notes, sound.wave, envelope, spb, sample_rate, level=0.3 * result.clip.gain, gate=result.clip.gate)
    sampled = np.zeros((total, 2))
    for start, segment, gain in samples:
        n = min(len(segment), total - start)
        if n > 0:
            sampled[start : start + n] += gain * segment[:n]

    beats = np.arange(total) / sample_rate / spb
    gain: np.ndarray | float = db_to_gain(track.volume_db)
    pan: np.ndarray | float = track.pan
    if track.gain_automation:
        try:
            gain = gain * np.clip(_automation(track.gain_automation, beats), 0.0, 4.0)
        except ValueError as exc:
            errors.append({**where, "field": "automation.gain", "error": str(exc)})
    if track.pan_automation:
        try:
            pan = np.clip(track.pan + _automation(track.pan_automation, beats), -1.0, 1.0)
        except ValueError as exc:
            errors.append({**where, "field": "automation.pan", "error": str(exc)})

    angle = (np.asarray(pan) + 1) * np.pi / 4  # equal-power pan; unity at centre for stereo samples
    left, right = np.cos(angle), np.sin(angle)
    stereo = np.stack(
        [
            gain * (mono * left + sampled[:, 0] * left * np.sqrt(2)),
            gain * (mono * right + sampled[:, 1] * right * np.sqrt(2)),
        ],
        axis=1,
    )
    stereo = apply_chain(stereo, track.effects, where, errors, spb, sample_rate, beats)
    return TrackRender(stereo=stereo.astype(np.float32), clips=clip_data, errors=errors)


class _TrackCache:
    """Least-recently-used cache of rendered tracks, bounded by memory."""

    def __init__(self, budget: int) -> None:
        self._budget = budget
        self._items: OrderedDict[str, TrackRender] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def _size(item: TrackRender) -> int:
        return item.stereo.nbytes if item.stereo is not None else 0

    def get(self, key: str) -> TrackRender | None:
        with self._lock:
            item = self._items.get(key)
            if item is not None:
                self._items.move_to_end(key)
            return item

    def put(self, key: str, item: TrackRender) -> None:
        with self._lock:
            self._items[key] = item
            self._items.move_to_end(key)
            while sum(self._size(v) for v in self._items.values()) > self._budget and len(self._items) > 1:
                self._items.popitem(last=False)


_CACHE = _TrackCache(CACHE_BYTES)


def _track_key(track: Track, index: int, project: Project, total: int, audible: bool, sample_rate: int) -> str:
    payload = {
        "track": track_to_dict(track),
        "index": index,
        "bpm": project.bpm,
        "root": project.root,
        "scale": project.scale,
        "total": total,
        "audible": audible,
        "rate": sample_rate,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


@dataclass
class ProjectRender:
    stereo: np.ndarray  # (samples, 2) float32
    length_beats: float
    tracks: list[dict]
    errors: list[dict]
    sample_rate: int = SAMPLE_RATE
    master_peaks: list[float] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.stereo.shape[0] / self.sample_rate


def render(project: Project, sample_rate: int = SAMPLE_RATE) -> ProjectRender:
    spb = 60.0 / project.bpm
    length = project.length_beats
    total = int(np.ceil((length * spb + TAIL_SECONDS) * sample_rate)) if length > 0 else 0
    any_solo = any(track.solo for track in project.tracks)

    mix = np.zeros((total, 2), dtype=np.float64)
    tracks: list[dict] = []
    errors: list[dict] = []
    rendered: list[TrackRender] = []
    for index, track in enumerate(project.tracks):
        audible = not track.mute and (track.solo or not any_solo)
        key = _track_key(track, index, project, total, audible, sample_rate)
        result = _CACHE.get(key)
        if result is None:
            result = _render_track(track, index, project, total, audible, sample_rate)
            _CACHE.put(key, result)
        rendered.append(result)
        if result.stereo is not None:
            mix += result.stereo
        sound = resolve_name(track.sound, index)
        tracks.append({"id": track.id, "sound": sound, "audible": audible, "clips": result.clips})
        errors.extend(result.errors)

    master_where = {"track": None, "clip": None}
    gain = db_to_gain(project.master.volume_db)
    if total:
        beats = np.arange(total) / sample_rate / spb
        mix = apply_chain(mix, project.master.effects, master_where, errors, spb, sample_rate, beats)
        mix *= gain
        if project.master.normalize:
            peak = float(np.abs(mix).max())
            if peak > 0:
                mix *= PEAK / peak
                gain *= PEAK / peak

    # levels for the UI, on the same scale as the final mix
    bucket = int(round(spb * sample_rate / PEAKS_PER_BEAT))
    for info, result in zip(tracks, rendered):
        info["peaks"] = peaks(result.stereo, bucket, gain)
    return ProjectRender(
        stereo=mix.astype(np.float32),
        length_beats=length,
        tracks=tracks,
        errors=errors,
        sample_rate=sample_rate,
        master_peaks=peaks(mix, bucket),
    )


def resolve_name(spec: str | None, index: int) -> str:
    """The display name of a track's sound, or the raw spec if it does not resolve."""
    try:
        return resolve(spec, index).name
    except ValueError:
        return spec or ""
