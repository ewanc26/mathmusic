"""Local graphing UI: serves the web app and a small JSON API.

Bound to 127.0.0.1 only. Rendering happens here with the same engine as the
CLI, so what you see in the graph is exactly what gets played and published.
"""

from __future__ import annotations

import json
import mimetypes
import os
import shutil
import tempfile
import threading
import uuid
import webbrowser
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from math import pi
from pathlib import Path
from urllib.parse import urlparse

import numpy as np

from mathmusic.composer import Options, build_voices
from mathmusic.expr import Expression, ExpressionError
from mathmusic.scales import SCALES, parse_note
from mathmusic.synth import SAMPLE_RATE, encode_mp3, mix, write_wav

WEB_DIR = Path(__file__).parent / "web"
MAX_SAMPLES = 2000
MAX_BODY = 1_000_000
MAX_RENDERS = 16
ALLOWED_RHYTHMS = ("uniform", "slope")


class RenderStore:
    """Keeps the most recent WAV renders on disk so audio and export can refer to them by id."""

    def __init__(self, limit: int = MAX_RENDERS) -> None:
        self._limit = limit
        self._items: OrderedDict[str, Path] = OrderedDict()
        self._lock = threading.Lock()
        self._dir = Path(tempfile.mkdtemp(prefix="mathmusic-"))

    def new_path(self) -> tuple[str, Path]:
        render_id = uuid.uuid4().hex[:12]
        return render_id, self._dir / f"{render_id}.wav"

    def add(self, render_id: str, wav: Path) -> None:
        with self._lock:
            self._items[render_id] = wav
            while len(self._items) > self._limit:
                _, old = self._items.popitem(last=False)
                old.unlink(missing_ok=True)
                old.with_suffix(".mp3").unlink(missing_ok=True)

    def get(self, render_id: str) -> Path | None:
        with self._lock:
            return self._items.get(render_id)

    def cleanup(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)


STORE = RenderStore()


def _number_or_none(value: float) -> float | None:
    """JSON has no NaN or Infinity, so undefined points become null."""
    return float(value) if np.isfinite(value) else None


def parse_options(raw: dict) -> Options:
    def number(key: str, default: float, low: float, high: float) -> float:
        value = float(raw.get(key, default))
        if not low <= value <= high:
            raise ValueError(f"{key} must be between {low} and {high}")
        return value

    samples = int(number("samples", 96, 2, MAX_SAMPLES))
    scale = str(raw.get("scale", "pentatonic"))
    if scale not in SCALES:
        raise ValueError(f"unknown scale {scale!r}")
    rhythm = str(raw.get("rhythm", "uniform"))
    if rhythm not in ALLOWED_RHYTHMS:
        raise ValueError(f"unknown rhythm {rhythm!r}")
    start = float(raw.get("start", 0.0))
    end = float(raw.get("end", 4 * pi))
    if end <= start:
        raise ValueError("end must be greater than start")

    return Options(
        start=start,
        end=end,
        samples=samples,
        scale=scale,
        root_midi=parse_note(str(raw.get("root", "C4"))),
        octaves=int(number("octaves", 2, 1, 4)),
        bpm=number("bpm", 120, 30, 300),
        step_beats=number("step", 0.5, 0.05, 4),
        rhythm=rhythm,
    )


def render_project(payload: dict) -> dict:
    opts = parse_options(payload.get("options") or {})
    expressions = payload.get("expressions") or []

    errors: list[dict] = []
    active: list[tuple[int, str, str | None]] = []
    for index, item in enumerate(expressions):
        source = str(item.get("src", "")).strip()
        if not source or not item.get("enabled", True):
            continue
        try:
            Expression(source)
        except ExpressionError as exc:
            errors.append({"index": index, "error": str(exc)})
            continue
        active.append((index, source, item.get("waveform")))

    response: dict = {"errors": errors, "voices": [], "audio": None, "duration": 0.0}
    if not active:
        return response

    voices = build_voices(
        [src for _, src, _ in active],
        opts,
        waveforms=[wave for _, _, wave in active],
    )
    for (index, _, _), voice in zip(active, voices):
        response["voices"].append(
            {
                "index": index,
                "expression": voice.expression.source,
                "waveform": voice.waveform,
                "pan": voice.pan,
                "samples": [
                    {
                        "x": float(x),
                        "y": _number_or_none(y),
                        "start": step.start,
                        "duration": step.duration,
                        "pitch": step.pitch,
                    }
                    for x, y, step in zip(voice.x, voice.y, voice.steps)
                ],
            }
        )

    stereo = mix(voices, opts.bpm, SAMPLE_RATE)
    if stereo.size:
        render_id, wav = STORE.new_path()
        write_wav(wav, stereo, SAMPLE_RATE)
        STORE.add(render_id, wav)
        response["audio"] = {"id": render_id, "url": f"/audio/{render_id}.wav"}
        response["duration"] = stereo.shape[0] / SAMPLE_RATE
    response["bpm"] = opts.bpm
    return response


def publish_project(payload: dict) -> dict:
    from mathmusic.publish import publish_to_plyr

    render_id = str(payload.get("render_id", ""))
    wav = STORE.get(render_id)
    if wav is None:
        raise LookupError("that render has expired; render again before publishing")
    title = str(payload.get("title", "")).strip()
    if not title:
        raise ValueError("a title is required")
    mp3 = _ensure_mp3(render_id, wav)
    tags = {t.strip() for t in str(payload.get("tags", "")).split(",") if t.strip()} or None
    album = str(payload.get("album", "")).strip() or None
    description = str(payload.get("description", "")).strip() or None
    track_id = publish_to_plyr(mp3, title, album=album, tags=tags, description=description)
    return {"track_id": track_id}


def _ensure_mp3(render_id: str, wav: Path) -> Path:
    mp3 = wav.with_suffix(".mp3")
    if not mp3.exists():
        encode_mp3(wav, mp3)
    return mp3


def status() -> dict:
    try:
        import plyrfm  # noqa: F401

        has_sdk = True
    except ImportError:
        has_sdk = False
    return {
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "plyrfm": has_sdk,
        "plyr_token": bool(os.environ.get("PLYR_TOKEN")),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "mathmusic"

    def log_message(self, format, *args):  # keep the terminal quiet
        pass

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._file(WEB_DIR / "index.html")
        if path.startswith("/static/"):
            return self._file(WEB_DIR / path.removeprefix("/static/"))
        if path == "/api/status":
            return self._json(200, status())
        if path.startswith("/audio/"):
            return self._audio(path.removeprefix("/audio/"))
        self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > MAX_BODY:
                return self._json(413, {"error": "request too large"})
            payload = json.loads(self.rfile.read(length) or b"{}")
            if path == "/api/render":
                return self._json(200, render_project(payload))
            if path == "/api/publish":
                return self._json(200, publish_project(payload))
            self.send_error(404)
        except (ValueError, ExpressionError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})
        except LookupError as exc:
            self._json(404, {"error": str(exc)})
        except RuntimeError as exc:
            self._json(502, {"error": str(exc)})
        except Exception as exc:  # report unexpected failures to the UI rather than dropping the connection
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def _audio(self, name: str) -> None:
        render_id, _, ext = name.rpartition(".")
        wav = STORE.get(render_id)
        if wav is None or ext not in ("wav", "mp3"):
            return self.send_error(404)
        target = wav if ext == "wav" else _ensure_mp3(render_id, wav)
        self._file(target, content_type="audio/wav" if ext == "wav" else "audio/mpeg")

    def _file(self, path: Path, content_type: str | None = None) -> None:
        try:
            data = path.read_bytes()
        except OSError:
            return self.send_error(404)
        ctype = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def serve(port: int = 8765, open_browser: bool = True) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    url = f"http://127.0.0.1:{port}/"
    print(f"mathmusic running at {url}  (ctrl-c to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        STORE.cleanup()
