"""Tests for the parts the DAW tests do not reach: publishing, plotting, the
EQ and compressor, imported-audio widths, the render store and the CLI."""

import io
import sys
import types
import wave
from pathlib import Path

import numpy as np
import pytest

from mathmusic.cli import main
from mathmusic.composer import Options, build_voices

SR = 8000


# ---------------------------------------------------------------- publishing


def _fake_plyrfm(monkeypatch, record: dict) -> None:
    class Tracks:
        def upload(self, path, title, *, album=None, tags=None, description=None):
            record.update(path=path, title=title, album=album, tags=tags, description=description)
            return types.SimpleNamespace(track_id=4242)

    class PlyrClient:
        def __init__(self, token):
            record["token"] = token
            self.tracks = Tracks()

    module = types.ModuleType("plyrfm")
    module.PlyrClient = PlyrClient
    monkeypatch.setitem(sys.modules, "plyrfm", module)


def test_publish_uploads_with_the_token(tmp_path, monkeypatch):
    record: dict = {}
    _fake_plyrfm(monkeypatch, record)
    monkeypatch.setenv("PLYR_TOKEN", "secret")
    from mathmusic.publish import publish_to_plyr

    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"not really audio")
    assert publish_to_plyr(audio, "Title", album="Album", tags={"math"}, description="notes") == 4242
    assert record["token"] == "secret"
    assert record["album"] == "Album" and record["tags"] == {"math"} and record["description"] == "notes"


def test_publish_needs_a_token(tmp_path, monkeypatch):
    _fake_plyrfm(monkeypatch, {})
    monkeypatch.delenv("PLYR_TOKEN", raising=False)
    from mathmusic.publish import publish_to_plyr

    with pytest.raises(RuntimeError, match="PLYR_TOKEN"):
        publish_to_plyr(tmp_path / "a.mp3", "Title")


def test_publish_needs_the_sdk(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "plyrfm", None)
    monkeypatch.setenv("PLYR_TOKEN", "secret")
    from mathmusic.publish import publish_to_plyr

    with pytest.raises(RuntimeError, match="plyrfm"):
        publish_to_plyr(tmp_path / "a.mp3", "Title")


# ---------------------------------------------------------------- plotting


def test_plot_voices_writes_a_png(tmp_path):
    pytest.importorskip("matplotlib")
    from mathmusic.plot import plot_voices

    voices = build_voices(["sin(x)", "x^2/8"], Options(samples=16))
    path = plot_voices(voices, tmp_path / "curves.png")
    assert path.exists() and path.stat().st_size > 1000


# ---------------------------------------------------------------- effects


def _sine(freq: float, seconds: float = 0.5) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return np.stack([np.sin(2 * np.pi * freq * t)] * 2, axis=1)


def test_eq_boosts_and_leaves_gain_zero_alone():
    from mathmusic import dsp

    tone = _sine(1000.0)
    boosted = dsp.eq(tone, 1000.0, 12.0, 1.0, SR)
    assert np.abs(boosted).max() > np.abs(tone).max()
    assert np.abs(dsp.eq(tone, 1000.0, 0.0, 1.0, SR) - tone).max() < 1e-9


def test_compressor_squashes_a_loud_signal():
    from mathmusic import dsp

    loud = 0.9 * _sine(200.0)
    squashed = dsp.compressor(loud, -18.0, 4.0, 10.0, 120.0, 0.0, SR)
    half = len(loud) // 2  # skip the attack transient and compare the steady state
    assert np.sqrt((squashed[half:] ** 2).mean()) < np.sqrt((loud[half:] ** 2).mean())


def test_apply_effect_rejects_unknown_kinds():
    from mathmusic import dsp

    with pytest.raises(ValueError, match="unknown effect"):
        dsp.apply_effect(_sine(200.0), "nope", {}, SR, 0.5)


def test_automated_eq_parameters_run():
    from mathmusic import dsp

    tone = _sine(500.0)
    sweep = np.linspace(200.0, 2000.0, len(tone))
    out = dsp.eq(tone, sweep, 6.0, 1.0, SR)
    assert out.shape == tone.shape and np.isfinite(out).all()


# ---------------------------------------------------------------- assets


def _wav_of_width(width: int, channels: int = 1, rate: int = 8000, frames: int = 1600) -> bytes:
    t = np.arange(frames) / rate
    sig = 0.5 * np.sin(2 * np.pi * 300 * t)
    if width == 1:
        data = (np.round(sig * 127) + 128).astype(np.uint8).tobytes()
    elif width == 2:
        data = (sig * 32767).astype("<i2").tobytes()
    elif width == 3:
        ints = np.round(sig * ((1 << 23) - 1)).astype(np.int64)
        data = b"".join(int(v & 0xFFFFFF).to_bytes(3, "little") for v in ints)
    else:
        data = (sig * (2**31 - 1)).astype("<i4").tobytes()
    if channels > 1:
        data = b"".join(bytes(data[i :: len(data) // channels]) for i in range(channels))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(width)
        out.setframerate(rate)
        out.writeframes(data)
    return buffer.getvalue()


@pytest.mark.parametrize("width", [1, 2, 3, 4])
def test_every_pcm_width_is_decoded_to_stereo(width, tmp_path, monkeypatch):
    from mathmusic import assets

    monkeypatch.setenv("MATHMUSIC_HOME", str(tmp_path))
    audio = assets.import_audio(_wav_of_width(width, rate=22050), "tone.wav")
    loaded = assets.load_asset(audio["id"])
    assert loaded.shape[1] == 2  # mono became stereo
    assert len(loaded) == pytest.approx(1600 * 44100 / 22050, abs=5)  # resampled to 44.1 kHz


def test_more_than_two_channels_is_truncated(tmp_path, monkeypatch):
    from mathmusic import assets

    monkeypatch.setenv("MATHMUSIC_HOME", str(tmp_path))
    audio = assets.import_audio(_wav_of_width(2, channels=4, rate=44100), "quad.wav")
    assert assets.load_asset(audio["id"]).shape[1] == 2


def test_empty_uploads_are_rejected(tmp_path, monkeypatch):
    from mathmusic import assets

    monkeypatch.setenv("MATHMUSIC_HOME", str(tmp_path))
    with pytest.raises(assets.AssetError, match="empty"):
        assets.import_audio(b"", "empty.wav")


# ---------------------------------------------------------------- render store


def test_render_store_evicts_and_cleans_up():
    from mathmusic.server import RenderStore

    store = RenderStore(limit=2)
    paths = []
    for _ in range(3):
        render_id, path = store.new_path()
        path.write_bytes(b"wav")
        store.add(render_id, path)
        paths.append(path)
    assert not paths[0].exists()  # the oldest render is dropped
    assert paths[1].exists() and paths[2].exists()
    assert store.get(render_id) == paths[2]
    store.cleanup()
    assert not store._dir.exists()


# ---------------------------------------------------------------- CLI


def test_cli_sketch_writes_audio(tmp_path):
    out = tmp_path / "sketch.wav"
    assert main(["sin(x)", "x^2/8", "--samples", "24", "-o", str(out)]) == 0
    assert out.exists() and out.stat().st_size > 1000


def test_cli_instruments_lists_the_catalogue(capsys):
    assert main(["instruments"]) == 0
    printed = capsys.readouterr().out
    assert "sine" in printed and "bell" in printed


def test_serve_command_takes_a_port(monkeypatch):
    from mathmusic import cli, server

    called: dict = {}
    monkeypatch.setattr(server, "serve", lambda port=8765, open_browser=True: called.update(port=port, open_browser=open_browser))
    assert cli.serve_main(["--port", "9123", "--no-browser"]) == 0
    assert called == {"port": 9123, "open_browser": False}


# ---------------------------------------------------------------- MIDI details


def test_midi_velocity_follows_the_clip_gain():
    from mathmusic.midi import project_to_midi
    from mathmusic.project import parse_project
    from test_daw import read_midi

    def velocity_for(gain):
        data = _song()
        data["tracks"][0]["clips"][0].update(gain=gain, notes=1)
        _, _, tracks = read_midi(project_to_midi(parse_project(data)))
        return [event[2][1] for event in tracks[1] if event[1] & 0xF0 == 0x90]

    assert velocity_for(0.5) == [50]
    assert velocity_for(1.0) == [100]
    assert velocity_for(2.0) == [127]  # clamped
    assert velocity_for(0.0) == [1]  # a silent clip still gets a note, at the minimum velocity


# ---------------------------------------------------------------- HTTP API extras


def _song(**overrides):
    project = {
        "name": "Test",
        "bpm": 120,
        "root": "C4",
        "scale": "major",
        "master": {"normalize": True},
        "tracks": [
            {"id": "t1", "name": "A", "sound": "sine",
             "clips": [{"id": "c1", "start": 0, "length": 4, "expression": "x", "x_start": 0, "x_end": 1, "notes": 4}]}
        ],
    }
    project.update(overrides)
    return project


def test_api_instruments_and_default_project(api):
    status, body = api("/api/instruments")
    waveforms = {item["name"] for item in body["waveforms"]}
    instruments = {item["name"] for item in body["instruments"]}
    assert status == 200 and "sine" in waveforms and "bell" in instruments
    status, body = api("/api/project/default")
    assert status == 200 and body["tracks"]


def test_api_oversized_body_is_413(api):
    # the server refuses on the declared length, before reading the body
    status, body = api("/api/project/render", "POST", {"x": 1}, headers={"Content-Length": "2000000"})
    assert status == 413 and "large" in body["error"]


def test_api_range_past_the_end_is_416(api):
    _, body = api("/api/project/render", "POST", {"project": _song()})
    status, _ = api(body["audio"]["url"], headers={"Range": "bytes=99999999-"})
    assert status == 416


def test_api_unexpected_failure_is_a_500_with_a_message(api, monkeypatch):
    import mathmusic.server as server

    def boom(payload):
        raise TypeError("engine exploded")

    monkeypatch.setattr(server, "render_daw", boom)
    status, body = api("/api/project/render", "POST", {"project": _song()})
    assert status == 500 and "engine exploded" in body["error"]


def test_api_publish_needs_a_live_render(api):
    status, body = api("/api/publish", "POST", {"render_id": "gone", "title": "T"})
    assert status == 404 and "expired" in body["error"]


def test_api_publish_needs_a_title(api):
    _, body = api("/api/project/render", "POST", {"project": _song()})
    status, body = api("/api/publish", "POST", {"render_id": body["audio"]["id"]})
    assert status == 400 and "title" in body["error"]


def test_api_publish_passes_the_metadata_through(api, monkeypatch):
    import mathmusic.publish as publish
    import mathmusic.server as server

    monkeypatch.setattr(server, "encode_mp3", lambda wav, mp3: mp3.write_bytes(b"ID3fake"))
    captured: dict = {}

    def fake_publish(path, title, *, album=None, tags=None, description=None):
        captured.update(title=title, album=album, tags=tags, description=description, encoded=path.exists())
        return 77

    monkeypatch.setattr(publish, "publish_to_plyr", fake_publish)
    _, body = api("/api/project/render", "POST", {"project": _song()})
    status, body = api(
        "/api/publish",
        "POST",
        {"render_id": body["audio"]["id"], "title": " My Song ", "album": " A ", "tags": "math, sine", "description": " notes "},
    )
    assert status == 200 and body == {"track_id": 77}
    assert captured == {"title": "My Song", "album": "A", "tags": {"math", "sine"}, "description": "notes", "encoded": True}
