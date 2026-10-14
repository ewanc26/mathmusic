"""Tests for the DAW layer: project model, effects, engine, storage and API."""

import json
import threading
import urllib.error
import urllib.request

import numpy as np
import pytest

from mathmusic import dsp, engine
from mathmusic.project import (
    LIMITS,
    ProjectError,
    default_project,
    parse_project,
    project_to_dict,
)

SR = 8000  # low sample rate keeps the tests fast


def small_project(**overrides) -> dict:
    project = {
        "name": "Test",
        "bpm": 120,
        "root": "C4",
        "scale": "major",
        "master": {"normalize": True},
        "tracks": [
            {
                "id": "t1",
                "name": "A",
                "sound": "sine",
                "clips": [{"id": "c1", "start": 0, "length": 4, "expression": "x", "x_start": 0, "x_end": 1, "notes": 4}],
            }
        ],
    }
    project.update(overrides)
    return project


# ---------------------------------------------------------------- project model


def test_default_project_round_trips():
    data = project_to_dict(default_project())
    assert project_to_dict(parse_project(data)) == data
    assert len(data["tracks"]) == 3


def test_project_length_is_the_last_clip_end():
    project = parse_project(small_project())
    assert project.length_beats == 4


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda p: p.update(bpm=0), "bpm"),
        (lambda p: p.update(scale="lydian-ish"), "scale"),
        (lambda p: p.update(root="H2"), "note"),
        (lambda p: p["tracks"][0]["clips"][0].update(x_end=-1), "x_end"),
        (lambda p: p["tracks"][0]["clips"][0].update(y_min=0), "y_min"),
        (lambda p: p["tracks"][0]["clips"][0].update(rhythm="swing"), "rhythm"),
        (lambda p: p["tracks"][0].update(id="../etc"), "id"),
        (lambda p: p["tracks"][0].update(effects=[{"type": "flanger"}]), "type"),
        (lambda p: p["tracks"][0].update(effects=[{"type": "delay", "params": {"feedback": 2}}]), "feedback"),
        (lambda p: p["tracks"][0]["clips"].append(dict(p["tracks"][0]["clips"][0])), "unique"),
        (lambda p: p["tracks"][0]["clips"][0].update(notes=LIMITS["notes_per_clip"] + 1), "notes"),
        (lambda p: p.update(version=99), "version"),
    ],
)
def test_invalid_projects_are_rejected(mutate, message):
    data = small_project()
    mutate(data)
    with pytest.raises(ProjectError, match=message):
        parse_project(data)


def test_too_many_tracks_rejected():
    data = small_project()
    data["tracks"] = [
        {"id": f"t{i}", "clips": []} for i in range(LIMITS["tracks"] + 1)
    ]
    with pytest.raises(ProjectError):
        parse_project(data)


def test_effect_params_get_defaults():
    data = small_project()
    data["tracks"][0]["effects"] = [{"type": "reverb"}]
    effect = parse_project(data).tracks[0].effects[0]
    assert effect.params == {"size": 0.6, "damping": 0.4, "mix": 0.25}


# ---------------------------------------------------------------- dsp


def impulse(n=SR):
    x = np.zeros((n, 2))
    x[0] = 1.0
    return x


def test_comb_matches_the_recurrence():
    x = np.random.default_rng(1).normal(size=200)
    expected = x.copy()
    for n in range(7, len(x)):
        expected[n] += 0.5 * expected[n - 7]
    assert np.allclose(dsp.comb(x, 7, 0.5), expected)


def test_delay_repeats_an_impulse_at_the_delay_time():
    out = dsp.delay(impulse(), samples=1000, feedback=0.5, mix=1.0)
    assert out[1000, 0] == pytest.approx(1.0)
    assert out[2000, 0] == pytest.approx(0.5)
    assert out[500, 0] == pytest.approx(0.0)


def test_lowpass_removes_high_frequency():
    t = np.arange(SR) / SR
    high = np.sin(2 * np.pi * 3000 * t)
    x = np.stack([high, high], axis=1)
    out = dsp.biquad(x, "lowpass", 200, 0.707, SR)
    assert np.abs(out[SR // 2 :]).max() < 0.05


def test_highpass_removes_low_frequency():
    t = np.arange(SR) / SR
    low = np.sin(2 * np.pi * 20 * t)
    x = np.stack([low, low], axis=1)
    out = dsp.biquad(x, "highpass", 2000, 0.707, SR)
    assert np.abs(out[SR // 2 :]).max() < 0.05


def test_reverb_adds_a_decaying_tail():
    out = dsp.reverb(impulse(), size=0.6, damping=0.3, mix=1.0, sample_rate=SR)
    early = np.abs(out[200:1200]).sum()
    late = np.abs(out[-1000:]).sum()
    assert early > 0 and late < early


def test_shaper_applies_the_formula_to_samples():
    x = np.array([[0.5, -0.5]])
    assert np.allclose(dsp.shaper(x, "x^2", 1.0), [[0.25, 0.25]])
    assert np.allclose(dsp.shaper(x, "1/x - 1/x", 0.5), [[0.25, -0.25]])  # NaN-free
    assert np.allclose(dsp.shaper(np.array([[0.0, 0.0]]), "1/x", 1.0), [[0.0, 0.0]])  # inf -> 0


# ---------------------------------------------------------------- engine


def test_render_produces_audio_and_clip_data():
    result = engine.render(parse_project(small_project()), sample_rate=SR)
    assert result.stereo.shape[1] == 2
    assert result.duration == pytest.approx(4 * 0.5 + engine.TAIL_SECONDS, abs=0.01)
    assert np.abs(result.stereo).max() == pytest.approx(0.89, abs=1e-3)
    clip = result.tracks[0]["clips"][0]
    assert [s["start"] for s in clip["samples"]] == [0, 1, 2, 3]
    assert result.errors == []


def test_clip_start_places_notes_on_the_timeline():
    data = small_project()
    data["tracks"][0]["clips"][0]["start"] = 8
    result = engine.render(parse_project(data), sample_rate=SR)
    assert result.tracks[0]["clips"][0]["samples"][0]["start"] == 8
    assert np.abs(result.stereo[: int(8 * 0.5 * SR) - 10]).max() == 0  # silent before the clip


def test_slope_rhythm_still_fills_the_clip_length():
    data = small_project()
    data["tracks"][0]["clips"][0].update(rhythm="slope", expression="x^3", notes=16)
    result = engine.render(parse_project(data), sample_rate=SR)
    samples = result.tracks[0]["clips"][0]["samples"]
    assert samples[-1]["start"] + samples[-1]["duration"] == pytest.approx(4)


def test_fixed_y_range_maps_values_to_absolute_pitches():
    data = small_project(scale="chromatic")
    clip = data["tracks"][0]["clips"][0]
    clip.update(y_min=0, y_max=2, octaves=1, expression="1", notes=2)  # constant 1 = middle of 0..2
    result = engine.render(parse_project(data), sample_rate=SR)
    assert {s["pitch"] for s in result.tracks[0]["clips"][0]["samples"]} == {66}


def test_bad_clip_formula_is_reported_and_others_still_play():
    data = small_project()
    data["tracks"][0]["clips"].append(
        {"id": "c2", "start": 4, "length": 4, "expression": "open('x')", "notes": 4}
    )
    result = engine.render(parse_project(data), sample_rate=SR)
    assert result.errors[0]["clip"] == "c2"
    assert result.stereo.size and np.abs(result.stereo).max() > 0


def test_mute_and_solo():
    data = small_project()
    data["tracks"].append(
        {"id": "t2", "sound": "square", "solo": True, "clips": [{"id": "c9", "start": 0, "length": 4, "notes": 4}]}
    )
    result = engine.render(parse_project(data), sample_rate=SR)
    audible = {t["id"]: t["audible"] for t in result.tracks}
    assert audible == {"t1": False, "t2": True}

    data["tracks"][1]["mute"] = True
    result = engine.render(parse_project(data), sample_rate=SR)
    assert np.abs(result.stereo).max() == 0  # the only soloed track is muted


def test_gain_automation_shapes_the_volume():
    data = small_project(master={"normalize": False})
    data["tracks"][0]["clips"][0].update(expression="1", notes=1, length=8)
    data["tracks"][0]["automation"] = {"gain": "max(0, 1 - x/4)"}  # fades to silence by beat 4
    result = engine.render(parse_project(data), sample_rate=SR)
    beat = int(0.5 * SR)
    assert np.abs(result.stereo[beat // 2 : beat]).max() > 0.05
    assert np.abs(result.stereo[5 * beat : 7 * beat]).max() == 0


def test_bad_automation_is_reported():
    data = small_project()
    data["tracks"][0]["automation"] = {"gain": "log(x - 100)"}
    result = engine.render(parse_project(data), sample_rate=SR)
    assert result.errors[0]["field"] == "automation.gain"


def test_bad_effect_formula_is_reported_and_skipped():
    data = small_project()
    data["tracks"][0]["effects"] = [{"type": "shaper", "params": {"formula": "import os"}}]
    result = engine.render(parse_project(data), sample_rate=SR)
    assert result.errors[0]["field"] == "effects[0]"
    assert np.abs(result.stereo).max() > 0


def test_pan_hard_left_silences_the_right_channel():
    data = small_project(master={"normalize": False})
    data["tracks"][0]["pan"] = -1
    result = engine.render(parse_project(data), sample_rate=SR)
    assert np.abs(result.stereo[:, 1]).max() < 1e-6
    assert np.abs(result.stereo[:, 0]).max() > 0.01


def test_track_cache_returns_identical_audio():
    project = parse_project(small_project())
    first = engine.render(project, sample_rate=SR)
    second = engine.render(project, sample_rate=SR)
    assert np.array_equal(first.stereo, second.stereo)


def test_empty_project_renders_silence():
    result = engine.render(parse_project(small_project(tracks=[])), sample_rate=SR)
    assert result.stereo.size == 0


# ---------------------------------------------------------------- storage


def test_save_list_and_load(tmp_path, monkeypatch):
    from mathmusic import storage

    monkeypatch.setenv("MATHMUSIC_HOME", str(tmp_path))
    storage.save_project("My Song", small_project())
    assert [p["name"] for p in storage.list_projects()] == ["My Song"]
    loaded = storage.load_project("My Song")
    assert loaded["name"] == "My Song"
    assert loaded["tracks"][0]["clips"][0]["expression"] == "x"


@pytest.mark.parametrize("name", ["../escape", "a/b", "", ".hidden", "x" * 65])
def test_unsafe_project_names_rejected(tmp_path, monkeypatch, name):
    from mathmusic import storage

    monkeypatch.setenv("MATHMUSIC_HOME", str(tmp_path))
    with pytest.raises(ValueError):
        storage.save_project(name, small_project())


def test_loading_a_missing_project(tmp_path, monkeypatch):
    from mathmusic import storage

    monkeypatch.setenv("MATHMUSIC_HOME", str(tmp_path))
    with pytest.raises(LookupError):
        storage.load_project("nope")


# ---------------------------------------------------------------- HTTP API


@pytest.fixture
def api(tmp_path, monkeypatch):
    from mathmusic.server import make_server

    monkeypatch.setenv("MATHMUSIC_HOME", str(tmp_path))
    server = make_server(0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def call(path, method="GET", body=None, headers=None):
        data = None if body is None else json.dumps(body).encode()
        hdrs = {"Content-Type": "application/json"} if body is not None else {}
        hdrs.update(headers or {})
        req = urllib.request.Request(base + path, method=method, data=data, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                raw = res.read()
                return res.status, (json.loads(raw) if res.headers.get_content_type() == "application/json" else raw)
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw)
            except ValueError:
                return exc.code, raw

    yield call
    server.shutdown()
    server.server_close()


def test_api_catalogue(api):
    status, body = api("/api/catalogue")
    assert status == 200
    assert set(body["effects"]) == {"shaper", "lowpass", "highpass", "delay", "reverb"}
    assert body["effects"]["delay"]["feedback"]["max"] == 0.95
    assert "pentatonic" in body["scales"]


def test_api_render_project(api):
    status, body = api("/api/project/render", "POST", {"project": small_project()})
    assert status == 200
    assert body["audio"]["url"].endswith(".wav")
    assert body["tracks"][0]["clips"][0]["samples"][0]["pitch"] is not None


def test_api_render_rejects_invalid_project(api):
    status, body = api("/api/project/render", "POST", {"project": small_project(bpm=-5)})
    assert status == 400 and "bpm" in body["error"]


def test_api_plot(api):
    status, body = api("/api/plot", "POST", {"formula": "1/x", "start": -1, "end": 1, "points": 3})
    assert status == 200
    assert body["y"] == [-1.0, None, 1.0]


def test_api_save_and_load_project(api):
    status, _ = api("/api/projects/Demo", "PUT", {"project": small_project()})
    assert status == 200
    status, body = api("/api/projects")
    assert [p["name"] for p in body["projects"]] == ["Demo"]
    status, body = api("/api/projects/Demo")
    assert body["name"] == "Demo"
    status, body = api("/api/projects/Missing")
    assert status == 404


def test_api_rejects_unsafe_project_name(api):
    status, _ = api("/api/projects/..%2F..%2Fescape", "PUT", {"project": small_project()})
    assert status == 400


def test_static_files_cannot_escape_the_web_folder(api):
    for path in ["/static/../server.py", "/static/..%2Fserver.py", "/static/%2E%2E/server.py"]:
        status, _ = api(path)
        assert status == 404, path
    status, _ = api("/static/app.css")
    assert status == 200


def test_put_requires_same_origin(api):
    status, _ = api("/api/projects/Demo", "PUT", {"project": small_project()}, headers={"Origin": "https://evil.example"})
    assert status == 403


# ---------------------------------------------------------------- levels, MIDI, ranges, CLI


def test_peaks_cover_the_song_at_the_ui_resolution():
    result = engine.render(parse_project(small_project()), sample_rate=SR)
    track_peaks = result.tracks[0]["peaks"]
    beats = result.duration / 0.5
    assert len(track_peaks) == pytest.approx(beats * engine.PEAKS_PER_BEAT, abs=2)
    assert max(result.master_peaks) == pytest.approx(0.89, abs=0.01)
    assert max(track_peaks) <= 0.9


def test_muted_track_has_no_peaks():
    data = small_project()
    data["tracks"][0]["mute"] = True
    result = engine.render(parse_project(data), sample_rate=SR)
    assert result.tracks[0]["peaks"] == []


def read_midi(data: bytes):
    """Minimal SMF reader: returns (format, tracks), each track a list of (tick, status, data bytes)."""
    import struct

    assert data[:4] == b"MThd"
    fmt, ntracks, ppq = struct.unpack(">HHH", data[8:14])
    pos = 14
    tracks = []
    for _ in range(ntracks):
        assert data[pos : pos + 4] == b"MTrk"
        length = struct.unpack(">I", data[pos + 4 : pos + 8])[0]
        body = data[pos + 8 : pos + 8 + length]
        pos += 8 + length
        events, i, tick = [], 0, 0
        while i < len(body):
            delta = 0
            while True:
                byte = body[i]
                i += 1
                delta = (delta << 7) | (byte & 0x7F)
                if byte < 0x80:
                    break
            tick += delta
            status = body[i]
            if status == 0xFF:
                kind, size = body[i + 1], body[i + 2]
                events.append((tick, 0xFF, bytes([kind]) + body[i + 3 : i + 3 + size]))
                i += 3 + size
            elif status & 0xF0 == 0xC0:
                events.append((tick, status, body[i + 1 : i + 2]))
                i += 2
            else:
                events.append((tick, status, body[i + 1 : i + 3]))
                i += 3
        tracks.append(events)
    return fmt, ppq, tracks


def test_midi_export_matches_the_audio_notes():
    from mathmusic.midi import PPQ, project_to_midi

    project = parse_project(small_project())
    fmt, ppq, tracks = read_midi(project_to_midi(project))
    assert fmt == 1 and ppq == PPQ and len(tracks) == 2
    tempo = next(e for e in tracks[0] if e[1] == 0xFF and e[2][0] == 0x51)
    assert int.from_bytes(tempo[2][1:], "big") == 500_000  # 120 bpm
    notes_on = [e for e in tracks[1] if e[1] & 0xF0 == 0x90]
    clip = engine.render(project, sample_rate=SR).tracks[0]["clips"][0]["samples"]
    assert [e[2][0] for e in notes_on] == [s["pitch"] for s in clip]
    assert [e[0] for e in notes_on] == [round(s["start"] * PPQ) for s in clip]
    offs = [e for e in tracks[1] if e[1] & 0xF0 == 0x80]
    assert len(offs) == len(notes_on)


def test_midi_skips_drum_channel_and_uses_gm_program():
    from mathmusic.midi import project_to_midi

    data = small_project()
    data["tracks"] = [
        {"id": f"t{i}", "sound": "bell", "clips": [{"id": f"c{i}", "notes": 1, "length": 1}]} for i in range(11)
    ]
    _, _, tracks = read_midi(project_to_midi(parse_project(data)))
    channels = {e[1] & 0x0F for t in tracks[1:] for e in t if e[1] & 0xF0 == 0x90}
    assert 9 not in channels and len(channels) == 11
    programs = {e[2][0] for t in tracks[1:] for e in t if e[1] & 0xF0 == 0xC0}
    assert programs == {14}  # tubular bells


def test_api_midi_download(api):
    status, body = api("/api/project/midi", "POST", {"project": small_project()})
    assert status == 200 and body[:4] == b"MThd"


@pytest.mark.parametrize(
    "header, expected",
    [
        (None, None),
        ("bytes=0-9", (0, 9)),
        ("bytes=90-", (90, 99)),
        ("bytes=-10", (90, 99)),
        ("bytes=50-500", (50, 99)),
        ("bytes=100-", "invalid"),
        ("bytes=5-1", "invalid"),
        ("bytes=0-1,4-5", None),
        ("items=0-1", None),
    ],
)
def test_parse_range(header, expected):
    from mathmusic.server import _parse_range

    assert _parse_range(header, 100) == expected


def test_audio_is_served_with_byte_ranges(api):
    _, body = api("/api/project/render", "POST", {"project": small_project()})
    url = body["audio"]["url"]
    status, chunk = api(url, headers={"Range": "bytes=0-11"})
    assert status == 206 and chunk[:4] == b"RIFF" and len(chunk) == 12


def test_cli_renders_a_project_file(tmp_path):
    from mathmusic.cli import main

    path = tmp_path / "song.json"
    path.write_text(json.dumps(small_project()))
    assert main(["render", str(path), "-o", str(tmp_path / "song.wav")]) == 0
    assert (tmp_path / "song.wav").stat().st_size > 1000
    assert main(["render", str(path), "-o", str(tmp_path / "song.mid")]) == 0
    assert (tmp_path / "song.mid").read_bytes()[:4] == b"MThd"
