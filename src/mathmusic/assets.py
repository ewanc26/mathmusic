"""Imported audio samples, stored by content.

An import is decoded to 44.1 kHz stereo 16-bit WAV (with ffmpeg when it is
installed, otherwise only WAV input is accepted) and saved as
$MATHMUSIC_HOME/assets/<sha256>.wav. Projects refer to samples by that id,
so the same sample is stored once and a project file stays small.
"""

from __future__ import annotations

import hashlib
import io
import re
import shutil
import subprocess
import tempfile
import threading
import wave
from collections import OrderedDict
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

from mathmusic.storage import projects_dir
from mathmusic.synth import SAMPLE_RATE

MAX_UPLOAD = 50 * 1024 * 1024
MAX_SECONDS = 600
_ID = re.compile(r"[0-9a-f]{64}")


class AssetError(ValueError):
    """The upload is not usable audio, or the asset does not exist."""


def assets_dir() -> Path:
    return projects_dir().parent / "assets"


def _path(asset_id: str) -> Path:
    if not _ID.fullmatch(asset_id or ""):
        raise AssetError("not a sample id")
    return assets_dir() / f"{asset_id}.wav"


def _read_wav(data: bytes) -> np.ndarray:
    """PCM WAV bytes -> float32 (samples, 2) at SAMPLE_RATE."""
    try:
        with wave.open(io.BytesIO(data)) as source:
            channels = source.getnchannels()
            width = source.getsampwidth()
            rate = source.getframerate()
            frames = source.readframes(source.getnframes())
    except (wave.Error, EOFError) as exc:
        raise AssetError(f"not a readable WAV file: {exc}") from None
    if width == 1:
        audio = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128) / 128
    elif width == 2:
        audio = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768
    elif width == 3:
        raw = np.frombuffer(frames, dtype=np.uint8).reshape(-1, 3)
        ints = (raw[:, 0].astype(np.int32) | (raw[:, 1].astype(np.int32) << 8) | (raw[:, 2].astype(np.int32) << 16))
        ints = np.where(ints >= 1 << 23, ints - (1 << 24), ints)
        audio = ints.astype(np.float32) / (1 << 23)
    elif width == 4:
        audio = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2**31
    else:
        raise AssetError(f"unsupported sample width {width}")
    audio = audio.reshape(-1, channels)
    if channels == 1:
        audio = np.repeat(audio, 2, axis=1)
    elif channels > 2:
        audio = audio[:, :2]
    if rate != SAMPLE_RATE:
        audio = resample_poly(audio, SAMPLE_RATE, rate, axis=0).astype(np.float32)
    return audio


def _decode(data: bytes, filename: str) -> np.ndarray:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return _read_wav(data)
    suffix = Path(filename).suffix[:8] if filename else ""
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / f"input{suffix}"
        target = Path(tmp) / "decoded.wav"
        source.write_bytes(data)
        result = subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-i", str(source), "-ac", "2", "-ar", str(SAMPLE_RATE),
             "-t", str(MAX_SECONDS), "-c:a", "pcm_s16le", str(target)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not target.exists():
            message = (result.stderr or "").strip().splitlines()[-1:] or ["unknown format"]
            raise AssetError(f"could not decode the file: {message[0]}")
        return _read_wav(target.read_bytes())


def _to_wav_bytes(audio: np.ndarray) -> bytes:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(pcm.tobytes())
    return buffer.getvalue()


def import_audio(data: bytes, filename: str = "") -> dict:
    """Decode, normalise to the project format, and store. Returns {id, seconds}."""
    if not data:
        raise AssetError("the file is empty")
    if len(data) > MAX_UPLOAD:
        raise AssetError(f"files over {MAX_UPLOAD // (1024 * 1024)} MB are not accepted")
    audio = _decode(data, filename)
    if not len(audio):
        raise AssetError("the file has no audio")
    if len(audio) > MAX_SECONDS * SAMPLE_RATE:
        raise AssetError(f"samples longer than {MAX_SECONDS // 60} minutes are not accepted")
    wav = _to_wav_bytes(audio)
    asset_id = hashlib.sha256(wav).hexdigest()
    path = _path(asset_id)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(wav)
        temporary.replace(path)
    return {"id": asset_id, "seconds": len(audio) / SAMPLE_RATE, "name": Path(filename).name[:80]}


class _AssetCache:
    def __init__(self, limit: int = 16) -> None:
        self._items: OrderedDict[str, np.ndarray] = OrderedDict()
        self._limit = limit
        self._lock = threading.Lock()

    def get(self, asset_id: str) -> np.ndarray:
        with self._lock:
            if asset_id in self._items:
                self._items.move_to_end(asset_id)
                return self._items[asset_id]
        path = _path(asset_id)
        if not path.is_file():
            raise AssetError(f"sample {asset_id[:12]}… is missing from {assets_dir()}")
        audio = _read_wav(path.read_bytes())
        with self._lock:
            self._items[asset_id] = audio
            while len(self._items) > self._limit:
                self._items.popitem(last=False)
        return audio


_CACHE = _AssetCache()


def load_asset(asset_id: str) -> np.ndarray:
    """float32 (samples, 2) at SAMPLE_RATE."""
    return _CACHE.get(asset_id)
