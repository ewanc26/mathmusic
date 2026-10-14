"""Render voices to audio and write WAV / MP3 files."""

from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np

from mathmusic.composer import Voice
from mathmusic.waves import TABLE_SIZE, envelope_values, wavetable

SAMPLE_RATE = 44100
PEAK = 0.89  # about -1 dBFS, leaves headroom for the MP3 encoder
_GRID = np.linspace(0.0, 1.0, TABLE_SIZE + 1)


def _midi_to_hz(pitch: int) -> float:
    return 440.0 * 2 ** ((pitch - 69) / 12)


def render_voice(voice: Voice, seconds_per_beat: float, sample_rate: int) -> np.ndarray:
    """Mono buffer for one voice."""
    if not voice.notes:
        return np.zeros(0, dtype=np.float32)
    table = wavetable(voice.wave_formula)
    last = max(note.start + note.duration for note in voice.notes)
    buffer = np.zeros(int(np.ceil(last * seconds_per_beat * sample_rate)) + sample_rate // 4)

    for note in voice.notes:
        duration = note.duration * seconds_per_beat
        n = max(1, int(duration * sample_rate))
        t = np.arange(n) / sample_rate
        # read one period of the wavetable at this pitch; the phase wraps at 1
        phase = (_midi_to_hz(note.pitch) * t) % 1.0
        wave = np.interp(phase, _GRID, table)
        shape = envelope_values(voice.envelope_formula, t / duration)
        # short attack and release so neighbouring notes do not click
        attack = min(0.01, duration / 4)
        release = min(0.05, duration / 2)
        guard = np.minimum(t / attack, 1.0) * np.minimum((duration - t) / release, 1.0)
        start = int(round(note.start * seconds_per_beat * sample_rate))
        buffer[start : start + n] += 0.3 * guard * shape * wave

    return buffer.astype(np.float32)


def mix(voices: list[Voice], bpm: float, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Mix all voices into a stereo float32 array of shape (samples, 2)."""
    seconds_per_beat = 60.0 / bpm
    buffers = [render_voice(v, seconds_per_beat, sample_rate) for v in voices]
    length = max((len(b) for b in buffers), default=0)
    stereo = np.zeros((length, 2), dtype=np.float32)

    for voice, buffer in zip(voices, buffers):
        # equal-power panning
        angle = (voice.pan + 1) * np.pi / 4
        stereo[: len(buffer), 0] += buffer * np.cos(angle)
        stereo[: len(buffer), 1] += buffer * np.sin(angle)

    peak = np.abs(stereo).max() if stereo.size else 0.0
    if peak > 0:
        stereo *= PEAK / peak
    return stereo


def write_wav(path: Path, stereo: np.ndarray, sample_rate: int = SAMPLE_RATE) -> Path:
    pcm = (np.clip(stereo, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        out.writeframes(pcm.tobytes())
    return path


def encode_mp3(wav_path: Path, mp3_path: Path, bitrate: str = "192k") -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is needed for MP3 output: brew install ffmpeg")
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(wav_path), "-codec:a", "libmp3lame", "-b:a", bitrate, str(mp3_path)],
        check=True,
    )
    return mp3_path
