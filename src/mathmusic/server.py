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
from urllib.parse import unquote, urlparse

import numpy as np

from mathmusic import assets, engine, storage
from mathmusic.composer import PITCH_MODES, Options, build_voices
from mathmusic.expr import Expression, ExpressionError
from mathmusic.project import (
    AUTOMATABLE,
    EFFECT_SPECS,
    LIMITS,
    MAX_FORMULA,
    default_project,
    parse_project,
    project_to_dict,
)
from mathmusic.scales import SCALES, parse_note
from mathmusic.synth import SAMPLE_RATE, encode_mp3, mix, write_wav
from mathmusic.waves import describe_all, resolve

WEB_DIR = Path(__file__).parent / "web"
MAX_SAMPLES = 2000
MAX_VOICES = 8
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
    pitch_mode = str(raw.get("pitch_mode", "shared"))
    if pitch_mode not in PITCH_MODES:
        raise ValueError(f"unknown pitch mode {pitch_mode!r}")
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
        pitch_mode=pitch_mode,
    )


def render_project(payload: dict) -> dict:
    opts = parse_options(payload.get("options") or {})
    expressions = payload.get("expressions") or []

    errors: list[dict] = []
    active: list[tuple[int, str, str | None, bool]] = []
    for index, item in enumerate(expressions):
        source = str(item.get("src", "")).strip()
        if not source or not item.get("enabled", True):
            continue
        try:
            Expression(source)
            resolve(item.get("waveform"), index)  # validates the sound before the whole render fails
        except ValueError as exc:  # ExpressionError is a ValueError
            errors.append({"index": index, "error": str(exc)})
            continue
        active.append((index, source, item.get("waveform"), bool(item.get("invert", False))))

    response: dict = {"errors": errors, "voices": [], "audio": None, "duration": 0.0}
    if not active:
        return response

    if len(active) > MAX_VOICES:
        raise ValueError(f"at most {MAX_VOICES} expressions can be rendered at once")

    voices = build_voices(
        [src for _, src, _, _ in active],
        opts,
        waveforms=[wave for _, _, wave, _ in active],
        inverts=[invert for _, _, _, invert in active],
    )
    for (index, _, _, _), voice in zip(active, voices):
        response["voices"].append(
            {
                "index": index,
                "expression": voice.expression.source,
                "waveform": voice.waveform,
                "instrument": voice.instrument,
                "inverted": voice.inverted,
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


MAX_PLOT_POINTS = 1000


def _parse_range(header: str | None, size: int):
    """A single 'bytes=a-b' range as (start, end) inclusive, None for the whole file, or 'invalid'."""
    if not header or not header.startswith("bytes=") or "," in header:
        return None
    first, _, last = header.removeprefix("bytes=").strip().partition("-")
    try:
        if first == "":  # suffix range: the last N bytes
            length = int(last)
            if length <= 0:
                return "invalid"
            return max(0, size - length), size - 1
        start = int(first)
        end = int(last) if last else size - 1
    except ValueError:
        return None
    if start >= size or start > end:
        return "invalid"
    return start, min(end, size - 1)


def catalogue() -> dict:
    """Everything the DAW UI needs to build its menus."""
    return {
        **describe_all(),
        "effects": {
            kind: {
                name: (
                    {"kind": "formula", "default": spec[1]}
                    if spec[0] == "formula"
                    else {
                        "kind": "number",
                        "default": spec[1],
                        "min": spec[2],
                        "max": spec[3],
                        "automatable": (kind, name) in AUTOMATABLE,
                    }
                )
                for name, spec in params.items()
            }
            for kind, params in EFFECT_SPECS.items()
        },
        "scales": SCALES,  # name -> semitone degrees, so the UI can draw the pitch lattice
        "limits": LIMITS,
    }


def render_daw(payload: dict) -> dict:
    project = parse_project(payload.get("project"))
    result = engine.render(project)
    response = {
        "tracks": result.tracks,
        "errors": result.errors,
        "length_beats": result.length_beats,
        "bpm": project.bpm,
        "duration": 0.0,
        "audio": None,
        "master_peaks": result.master_peaks,
        "peaks_per_beat": engine.PEAKS_PER_BEAT,
    }
    if result.stereo.size:
        render_id, wav = STORE.new_path()
        write_wav(wav, result.stereo, SAMPLE_RATE)
        STORE.add(render_id, wav)
        response["audio"] = {"id": render_id, "url": f"/audio/{render_id}.wav"}
        response["duration"] = result.duration
    return response


def plot_formula(payload: dict) -> dict:
    """Sample any formula in x, so every formula in the UI can be drawn."""
    formula = str(payload.get("formula", ""))
    if len(formula) > MAX_FORMULA:
        raise ValueError(f"formula is longer than {MAX_FORMULA} characters")
    start = float(payload.get("start", 0.0))
    end = float(payload.get("end", 1.0))
    points = int(payload.get("points", 200))
    if not (np.isfinite(start) and np.isfinite(end)) or end <= start:
        raise ValueError("end must be greater than start")
    if not 2 <= points <= MAX_PLOT_POINTS:
        raise ValueError(f"points must be between 2 and {MAX_PLOT_POINTS}")
    x = np.linspace(start, end, points)
    y = Expression(formula).evaluate(x)
    return {"x": x.tolist(), "y": [_number_or_none(v) for v in y]}


class Handler(BaseHTTPRequestHandler):
    server_version = "mathmusic"

    def log_message(self, format, *args):  # keep the terminal quiet
        pass

    def _request_allowed(self) -> bool:
        """Reject DNS-rebinding and cross-site requests.

        Only the loopback host names for this port are accepted. A browser
        request from another site carries that site's Origin, so it is refused.
        """
        host = self.headers.get("Host", "")
        if host not in self.server.allowed_hosts:
            self._json(403, {"error": "unexpected Host header"})
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin != f"http://{host}":
            self._json(403, {"error": "cross-origin requests are not allowed"})
            return False
        return True

    def do_GET(self) -> None:
        if not self._request_allowed():
            return
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            return self._handle(lambda: self._get_api(path))
        if path.startswith("/audio/"):
            return self._audio(path.removeprefix("/audio/"))
        # the built UI (frontend/, SvelteKit): index.html plus its files under /_app/
        return self._static("index.html" if path in ("/", "") else path.lstrip("/"))

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/assets":
            return self._upload()
        if path == "/api/project/midi":
            return self._handle_json(self._midi, raw=True)
        self._handle_json(self._post_api)

    def _upload(self) -> None:
        """Import an audio file sent as the raw request body."""
        if not self._request_allowed():
            return
        # application/octet-stream is not a CORS "simple" type, so a cross-site upload needs a preflight
        if not self.headers.get("Content-Type", "").startswith("application/octet-stream"):
            return self._json(415, {"error": "upload the file as application/octet-stream"})
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > assets.MAX_UPLOAD:
            return self._json(413, {"error": f"files over {assets.MAX_UPLOAD // (1024 * 1024)} MB are not accepted"})
        filename = unquote(self.headers.get("X-Filename", ""))[:200]
        self._handle(lambda: assets.import_audio(self.rfile.read(length), filename))

    def _midi(self, path: str, payload: dict) -> None:
        from mathmusic.midi import project_to_midi

        project = parse_project(payload.get("project"))
        data = project_to_midi(project)
        self.send_response(200)
        self.send_header("Content-Type", "audio/midi")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_PUT(self) -> None:
        self._handle_json(self._put_api)

    def _get_api(self, path: str) -> dict:
        if path == "/api/status":
            return status()
        if path == "/api/instruments":
            return describe_all()
        if path == "/api/catalogue":
            return catalogue()
        if path == "/api/project/default":
            return project_to_dict(default_project())
        if path == "/api/projects":
            return {"projects": storage.list_projects(), "folder": str(storage.projects_dir())}
        if path.startswith("/api/projects/"):
            return storage.load_project(unquote(path.removeprefix("/api/projects/")))
        raise FileNotFoundError(path)

    def _post_api(self, path: str, payload: dict) -> dict:
        if path == "/api/render":
            return render_project(payload)
        if path == "/api/project/render":
            return render_daw(payload)
        if path == "/api/plot":
            return plot_formula(payload)
        if path == "/api/publish":
            return publish_project(payload)
        raise FileNotFoundError(path)

    def _put_api(self, path: str, payload: dict) -> dict:
        if path.startswith("/api/projects/"):
            return storage.save_project(unquote(path.removeprefix("/api/projects/")), payload.get("project"))
        raise FileNotFoundError(path)

    def _handle_json(self, route, raw: bool = False) -> None:
        """Parse a JSON body and run `route`. With raw=True the route writes its own response."""
        if not self._request_allowed():
            return
        path = urlparse(self.path).path
        # Requiring JSON forces a CORS preflight for any cross-site request.
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            return self._json(415, {"error": "requests must be application/json"})
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > MAX_BODY:
            return self._json(413, {"error": "request too large"})

        def run() -> dict:
            payload = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(payload, dict):
                raise ValueError("request body must be a JSON object")
            return route(path, payload)

        self._handle(run, raw=raw)

    def _handle(self, run, raw: bool = False) -> None:
        """Run an API call and map exceptions to HTTP status codes."""
        try:
            body = run()
            if raw:
                return
        except FileNotFoundError:
            return self._json(404, {"error": "not found"})
        except LookupError as exc:
            return self._json(404, {"error": str(exc).strip("'\"")})
        except (ValueError, ExpressionError) as exc:  # includes JSONDecodeError and ProjectError
            return self._json(400, {"error": str(exc)})
        except RuntimeError as exc:
            return self._json(502, {"error": str(exc)})
        except Exception as exc:  # report unexpected failures to the UI rather than dropping the connection
            return self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
        self._json(200, body)

    def _static(self, relative: str) -> None:
        root = WEB_DIR.resolve()
        target = (root / unquote(relative)).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            if relative == "index.html":
                return self._json(503, {"error": "the UI is not built; run `pnpm build` in frontend/"})
            return self.send_error(404)
        self._file(target)

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
        # Byte ranges make audio seekable: browsers will not seek media served without them.
        span = _parse_range(self.headers.get("Range"), len(data))
        if span == "invalid":
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{len(data)}")
            self.end_headers()
            return
        if span is None:
            self.send_response(200)
            body = data
        else:
            start, end = span
            body = data[start : end + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    # The UI loads its modules in one burst; the default backlog of 5 resets some connections.
    request_queue_size = 128


def make_server(port: int) -> ThreadingHTTPServer:
    server = _Server(("127.0.0.1", port), Handler)
    bound = server.server_address[1]  # differs from `port` when port is 0
    server.allowed_hosts = {f"127.0.0.1:{bound}", f"localhost:{bound}"}
    return server


def serve(port: int = 8765, open_browser: bool = True) -> None:
    server = make_server(port)
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
