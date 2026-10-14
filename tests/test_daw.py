"""Tests for the DAW layer: project model, effects, engine, storage and API."""

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

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


@pytest.mark.parametrize("expression", ["max(x)", "sin(x, 2)"])
def test_formula_errors_that_are_not_value_errors_are_contained(expression):
    data = small_project()
    data["tracks"][0]["clips"].append(
        {"id": "c3", "start": 4, "length": 4, "expression": expression, "notes": 4}
    )
    result = engine.render(parse_project(data), sample_rate=SR)
    assert any(error["clip"] == "c3" for error in result.errors)
    assert np.abs(result.stereo).max() > 0
def test_bad_arity_formula_is_reported_not_raised():
    # min(x) parses but calls the whitelisted minimum() with too few arguments;
    # it must be reported against its clip, not escape as a TypeError
    data = small_project()
    data["tracks"][0]["clips"].append(
        {"id": "c2", "start": 4, "length": 4, "expression": "min(x)", "notes": 4}
    )
    result = engine.render(parse_project(data), sample_rate=SR)
    assert [e["clip"] for e in result.errors] == ["c2"]
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


def test_default_home_is_ewanc26(monkeypatch):
    from mathmusic import storage

    monkeypatch.delenv("MATHMUSIC_HOME", raising=False)
    assert storage.projects_dir() == Path.home() / ".ewanc26" / "mathmusic" / "projects"


# ---------------------------------------------------------------- HTTP API

# the `api` fixture (a live server on a throwaway home) lives in conftest.py


def test_api_catalogue(api):
    status, body = api("/api/catalogue")
    assert status == 200
    assert set(body["effects"]) == {"shaper", "lowpass", "highpass", "delay", "reverb", "eq", "compressor"}
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


def test_api_reports_bad_arity_formula_instead_of_crashing(api):
    # a formula that parses but cannot run is a per-clip error, not a 500
    data = small_project()
    data["tracks"][0]["clips"][0]["expression"] = "min(x)"
    status, body = api("/api/project/render", "POST", {"project": data})
    assert status == 200
    assert body["tracks"][0]["clips"][0]["error"]

    status, body = api("/api/plot", "POST", {"formula": "min(x)", "start": 0, "end": 1})
    assert status == 400 and "min" in body["error"]


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
    for path in ["/../server.py", "/..%2Fserver.py", "/%2E%2E/server.py", "/_app/..%2F..%2Fserver.py"]:
        status, _ = api(path)
        assert status == 404, path
    status, page = api("/")
    assert status == 200 and b"<html" in page
    status, _ = api("/favicon.svg")
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


def test_midi_names_are_valid_utf8_when_truncated():
    from mathmusic.midi import project_to_midi

    data = small_project(name="Song")
    data["tracks"] = [{"id": "t1", "name": "a" + "é" * 60, "sound": "sine", "clips": []}]  # 121 bytes
    _, _, tracks = read_midi(project_to_midi(parse_project(data)))
    names = [bytes(e[2]).decode("utf-8") for e in tracks[1] if e[1] == 0xFF and e[2][0] == 0x03]
    assert names and len(names[0].encode("utf-8")) <= 120
def test_midi_never_stacks_the_same_pitch():
    from mathmusic.midi import project_to_midi

    data = small_project()
    data["tracks"] = [
        {
            "id": "t1",
            "sound": "sine",
            "clips": [
                {"id": "c1", "start": 0, "length": 4, "notes": 1, "expression": "x", "gate": 1},
                {"id": "c2", "start": 0.5, "length": 1, "notes": 1, "expression": "x", "gate": 1},
                {"id": "c3", "start": 0.5, "length": 1, "notes": 1, "expression": "x", "gate": 0.5},
            ],
        }
    ]
    _, _, tracks = read_midi(project_to_midi(parse_project(data)))
    per_pitch: dict[int, list[int]] = {}
    for tick, status, body in tracks[1]:
        if status & 0xF0 in (0x80, 0x90):
            kind = 1 if status & 0xF0 == 0x90 and body[1] else 0
            per_pitch.setdefault(body[0], []).append(kind)
    for pitch, kinds in per_pitch.items():
        # every note-on is followed by its note-off before the next note-on
        assert kinds == [1, 0] * (len(kinds) // 2), (pitch, kinds)
        assert kinds.count(1) >= 1


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
    status, chunk = api(url, headers={"Range": "bytes=0-11"})  # seekable audio
    assert status == 206 and chunk[:4] == b"RIFF" and len(chunk) == 12


def test_cli_renders_a_project_file(tmp_path):
    from mathmusic.cli import main

    path = tmp_path / "song.json"
    path.write_text(json.dumps(small_project()))
    assert main(["render", str(path), "-o", str(tmp_path / "song.wav")]) == 0
    assert (tmp_path / "song.wav").stat().st_size > 1000
    assert main(["render", str(path), "-o", str(tmp_path / "song.mid")]) == 0
    assert (tmp_path / "song.mid").read_bytes()[:4] == b"MThd"


# ---------------------------------------------------------------- audio accuracy


def dominant_frequency(mono: np.ndarray, sample_rate: int) -> float:
    spectrum = np.abs(np.fft.rfft(mono * np.hanning(len(mono))))
    return float(np.fft.rfftfreq(len(mono), 1 / sample_rate)[np.argmax(spectrum)])


@pytest.mark.parametrize("root, expected_hz", [("A4", 440.0), ("C4", 261.63), ("A3", 220.0)])
def test_rendered_note_has_the_right_pitch(root, expected_hz):
    """A constant curve plays the middle of a one-note range: the root. Check the audio, not just the numbers."""
    data = small_project(root=root, scale="chromatic", master={"normalize": False})
    data["tracks"][0]["clips"][0].update(expression="0", notes=1, length=4, octaves=1, y_min=0, y_max=1)
    sample_rate = 22050
    result = engine.render(parse_project(data), sample_rate=sample_rate)
    note = result.stereo[sample_rate // 4 : sample_rate, 0]  # the steady part of the note
    assert dominant_frequency(note, sample_rate) == pytest.approx(expected_hz, rel=0.01)


def test_rendered_notes_follow_the_curve_upwards():
    data = small_project(scale="chromatic", master={"normalize": False})
    data["tracks"][0]["clips"][0].update(expression="x", notes=4, length=8, x_start=0, x_end=1, octaves=1)
    sample_rate = 22050
    result = engine.render(parse_project(data), sample_rate=sample_rate)
    beat = int(0.5 * sample_rate)  # 120 bpm
    freqs = [dominant_frequency(result.stereo[i * 2 * beat + beat // 4 : i * 2 * beat + beat, 0], sample_rate) for i in range(4)]
    assert freqs == sorted(freqs) and freqs[-1] / freqs[0] == pytest.approx(2.0, rel=0.03)  # one octave


# ---------------------------------------------------------------- time signature, automation, samples


def test_time_signature_is_validated_and_exported_to_midi():
    from mathmusic.midi import project_to_midi

    with pytest.raises(ProjectError, match="beats_per_bar"):
        parse_project(small_project(beats_per_bar=0))
    _, _, tracks = read_midi(project_to_midi(parse_project(small_project(beats_per_bar=7))))
    signature = next(e for e in tracks[0] if e[1] == 0xFF and e[2][0] == 0x58)
    assert signature[2][1] == 7


def test_effect_params_can_be_formulas_of_the_beat():
    data = small_project()
    data["tracks"][0]["effects"] = [{"type": "lowpass", "params": {"cutoff": "200 + 100*x"}}]
    effect = parse_project(data).tracks[0].effects[0]
    assert effect.params["cutoff"] == "200 + 100*x"
    data["tracks"][0]["effects"] = [{"type": "delay", "params": {"time": "x"}}]  # time is not automatable
    with pytest.raises(ProjectError, match="time"):
        parse_project(data)


def test_filter_sweep_opens_over_time():
    """A lowpass whose cutoff rises from 100 Hz to 8 kHz lets more of a 2 kHz tone through later."""
    sample_rate = 22050
    t = np.arange(4 * sample_rate) / sample_rate
    tone = np.sin(2 * np.pi * 2000 * t)
    x = np.stack([tone, tone], axis=1)
    cutoff = np.linspace(100, 8000, len(t))
    out = dsp.biquad(x, "lowpass", cutoff, 0.707, sample_rate)
    # 0.05-0.2 s: the cutoff is still 200-500 Hz, far below the tone; by 3 s it is ~6 kHz
    early = np.abs(out[int(0.05 * sample_rate) : int(0.2 * sample_rate), 0]).max()
    late = np.abs(out[3 * sample_rate :, 0]).max()
    assert early < 0.15 and late > 0.8


def test_bad_effect_automation_is_reported():
    data = small_project()
    data["tracks"][0]["effects"] = [{"type": "reverb", "params": {"mix": "log(x - 100)"}}]
    result = engine.render(parse_project(data), sample_rate=SR)
    assert result.errors[0]["field"] == "effects[0]"


def wav_bytes(seconds=1.0, rate=22050, freq=440.0, channels=1):
    import io
    import wave

    t = np.arange(int(seconds * rate)) / rate
    pcm = (0.5 * np.sin(2 * np.pi * freq * t) * 32767).astype("<i2")
    if channels == 2:
        pcm = np.repeat(pcm, 2)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm.tobytes())
    return buffer.getvalue()


def test_import_audio_normalises_and_dedupes(tmp_path, monkeypatch):
    from mathmusic import assets

    monkeypatch.setenv("MATHMUSIC_HOME", str(tmp_path))
    first = assets.import_audio(wav_bytes(), "tone.wav")
    again = assets.import_audio(wav_bytes(), "copy.wav")
    assert first["id"] == again["id"]
    assert first["seconds"] == pytest.approx(1.0, abs=0.01)
    audio = assets.load_asset(first["id"])
    assert audio.shape[1] == 2  # mono became stereo
    assert len(audio) == pytest.approx(44100, abs=50)  # resampled to 44.1 kHz
    with pytest.raises(assets.AssetError):
        assets.import_audio(b"not audio at all", "junk.wav")


def test_wav_without_a_sample_rate_is_a_clear_error():
    import struct

    from mathmusic import assets

    data = b"\x00\x00" * 100
    fmt = struct.pack("<HHIIHH", 1, 2, 0, 0, 4, 16)  # PCM, stereo, rate 0
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(data)) + data
    # the built-in WAV reader, used when ffmpeg isn't installed
    with pytest.raises(assets.AssetError, match="sample rate"):
        assets._read_wav(b"RIFF" + struct.pack("<I", len(body)) + body)


def test_audio_clip_plays_its_sample_at_its_position(tmp_path, monkeypatch):
    from mathmusic import assets

    monkeypatch.setenv("MATHMUSIC_HOME", str(tmp_path))
    asset = assets.import_audio(wav_bytes(seconds=1.0, freq=330.0), "tone.wav")["id"]
    data = small_project(master={"normalize": False})
    data["tracks"][0]["clips"] = [{"id": "a1", "kind": "audio", "asset": asset, "start": 2, "length": 1}]  # beat 2 = 1 s
    result = engine.render(parse_project(data))
    rate = result.sample_rate
    assert np.abs(result.stereo[: rate - 100]).max() == 0  # silent before 1 s
    tone = result.stereo[rate + 1000 : rate + 10000, 0]
    assert dominant_frequency(tone, rate) == pytest.approx(330.0, rel=0.02)
    assert np.abs(result.stereo[int(1.6 * rate) :]).max() < 1e-6  # trimmed to 1 beat = 0.5 s
    clip = result.tracks[0]["clips"][0]
    assert clip["kind"] == "audio" and clip["peaks"]


def test_audio_clip_offset_skips_into_the_sample(tmp_path, monkeypatch):
    from mathmusic import assets

    monkeypatch.setenv("MATHMUSIC_HOME", str(tmp_path))
    asset = assets.import_audio(wav_bytes(seconds=1.0), "tone.wav")["id"]
    data = small_project(master={"normalize": False})
    data["tracks"][0]["clips"] = [{"id": "a1", "kind": "audio", "asset": asset, "start": 0, "length": 4, "offset": 1}]
    result = engine.render(parse_project(data))
    rate = result.sample_rate
    # 1 s of sample minus a 0.5 s offset leaves 0.5 s of sound
    assert np.abs(result.stereo[int(0.4 * rate) : int(0.45 * rate)]).max() > 0.1
    assert np.abs(result.stereo[int(0.55 * rate) :]).max() < 1e-6


def test_missing_sample_is_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("MATHMUSIC_HOME", str(tmp_path))
    data = small_project()
    data["tracks"][0]["clips"].append({"id": "a1", "kind": "audio", "asset": "0" * 64, "start": 0, "length": 4})
    result = engine.render(parse_project(data), sample_rate=SR)
    assert result.errors[0]["clip"] == "a1" and result.errors[0]["field"] == "asset"
    assert np.abs(result.stereo).max() > 0  # the curve clip still plays


def test_audio_clips_need_a_valid_asset_and_skip_midi():
    from mathmusic.midi import project_to_midi

    data = small_project()
    data["tracks"][0]["clips"].append({"id": "a1", "kind": "audio", "asset": "../../etc", "start": 0, "length": 4})
    with pytest.raises(ProjectError, match="asset"):
        parse_project(data)
    data["tracks"][0]["clips"][1]["asset"] = "f" * 64
    _, _, tracks = read_midi(project_to_midi(parse_project(data)))
    assert len([e for e in tracks[1] if e[1] & 0xF0 == 0x90]) == 4  # only the curve clip's notes


def api_upload(api, data: bytes, filename: str, content_type="application/octet-stream", origin=None):
    """POST raw bytes to the sample import endpoint."""
    headers = {"Content-Type": content_type, "X-Filename": filename}
    if origin:
        headers["Origin"] = origin
    req = urllib.request.Request(api.base + "/api/assets", method="POST", data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_api_upload_audio(api):
    status, body = api_upload(api, wav_bytes(), "tone.wav")
    assert status == 200 and len(body["id"]) == 64 and body["name"] == "tone.wav"
    status, _ = api_upload(api, wav_bytes(), "tone.wav", content_type="text/plain")
    assert status == 415
    status, _ = api_upload(api, wav_bytes(), "tone.wav", origin="https://evil.example")
    assert status == 403


@pytest.mark.skipif(__import__("shutil").which("ffmpeg") is None, reason="needs ffmpeg")
def test_import_decodes_browser_recordings(tmp_path, monkeypatch):
    """Microphone takes arrive as WebM/Opus from MediaRecorder; ffmpeg decodes them."""
    import subprocess

    from mathmusic import assets

    monkeypatch.setenv("MATHMUSIC_HOME", str(tmp_path))
    source = tmp_path / "tone.wav"
    source.write_bytes(wav_bytes(seconds=1.0, rate=48000, freq=440.0))
    take = tmp_path / "take.webm"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(source), "-c:a", "libopus", str(take)], check=True
    )
    asset = assets.import_audio(take.read_bytes(), "take.webm")
    assert asset["seconds"] == pytest.approx(1.0, abs=0.05)
    audio = assets.load_asset(asset["id"])
    assert dominant_frequency(audio[4410:30000, 0], 44100) == pytest.approx(440.0, rel=0.01)


# ---------------------------------------------------------------- EQ and compressor


def sine(freq, seconds=1.0, rate=22050):
    t = np.arange(int(seconds * rate)) / rate
    mono = np.sin(2 * np.pi * freq * t)
    return np.stack([mono, mono], axis=1)


def steady_gain(out, x, rate=22050):
    """Output amplitude over the steady part relative to the input's."""
    tail = slice(rate // 2, None)
    return np.abs(out[tail, 0]).max() / np.abs(x[tail, 0]).max()


def test_peaking_eq_boosts_its_centre_and_leaves_the_rest():
    rate = 22050
    boost = dsp.eq(sine(1000, rate=rate), 1000.0, 12.0, 1.0, rate)
    assert steady_gain(boost, sine(1000, rate=rate)) == pytest.approx(10 ** (12 / 20), rel=0.03)
    far = dsp.eq(sine(100, rate=rate), 1000.0, 12.0, 1.0, rate)
    assert steady_gain(far, sine(100, rate=rate)) == pytest.approx(1.0, rel=0.05)


def test_peaking_eq_cut_is_the_mirror_of_boost():
    rate = 22050
    cut = dsp.eq(sine(1000, rate=rate), 1000.0, -12.0, 1.0, rate)
    assert steady_gain(cut, sine(1000, rate=rate)) == pytest.approx(10 ** (-12 / 20), rel=0.03)


def test_compressor_reduces_loud_material_by_its_ratio():
    rate = 22050
    loud = 0.8 * sine(440, seconds=2.0, rate=rate)  # about -2 dBFS peak
    out = dsp.compressor(loud, threshold_db=-20.0, ratio=4.0, attack_ms=5, release_ms=50, makeup_db=0.0, sample_rate=rate)
    level_in = 20 * np.log10(0.8)
    level_out = 20 * np.log10(np.abs(out[rate:, 0]).max())
    # the input peak is ~18 dB over the threshold; 4:1 keeps a quarter of that.
    # The peak detector trails each sine peak slightly, so allow about 1 dB.
    assert level_out == pytest.approx(-20 + (level_in + 20) / 4, abs=1.0)


def test_compressor_leaves_quiet_material_alone():
    rate = 22050
    quiet = 0.05 * sine(440, seconds=1.0, rate=rate)
    out = dsp.compressor(quiet, threshold_db=-20.0, ratio=8.0, attack_ms=5, release_ms=50, makeup_db=0.0, sample_rate=rate)
    assert np.abs(out[rate // 2 :, 0]).max() == pytest.approx(np.abs(quiet[rate // 2 :, 0]).max(), rel=0.01)


def test_eq_and_compressor_are_reachable_as_effects_and_reported_in_the_engine():
    data = small_project(master={"normalize": False})
    data["tracks"][0]["effects"] = [
        {"type": "eq", "params": {"freq": 800, "gain": 6, "q": 1}},
        {"type": "compressor", "params": {"threshold": -12}},
    ]
    result = engine.render(parse_project(data), sample_rate=SR)
    assert result.errors == [] and np.abs(result.stereo).max() > 0


# ---------------------------------------------------------------- fades, swing, buses


def test_audio_clip_fade_in_and_out_shape_the_gain(tmp_path, monkeypatch):
    from mathmusic import assets

    monkeypatch.setenv("MATHMUSIC_HOME", str(tmp_path))
    asset = assets.import_audio(wav_bytes(seconds=2.0, freq=440.0), "tone.wav")["id"]
    data = small_project(master={"normalize": False})
    # a 4-beat clip (2 s at 120 bpm) with a 1-beat fade in and out
    data["tracks"][0]["clips"] = [
        {"id": "a1", "kind": "audio", "asset": asset, "start": 0, "length": 4, "fade_in": 1, "fade_out": 1}
    ]
    result = engine.render(parse_project(data))
    rate = result.sample_rate
    assert np.abs(result.stereo[: int(0.02 * rate), 0]).max() < 0.05  # starts near silence
    middle = np.abs(result.stereo[int(0.9 * rate) : int(1.1 * rate), 0]).max()
    assert middle > 0.3  # full level in the middle
    end = np.abs(result.stereo[int(1.95 * rate) : int(2.0 * rate), 0]).max()
    assert end < 0.05  # fades out to the end


def test_fade_curve_is_a_formula(tmp_path, monkeypatch):
    from mathmusic import assets

    monkeypatch.setenv("MATHMUSIC_HOME", str(tmp_path))
    asset = assets.import_audio(wav_bytes(seconds=2.0), "tone.wav")["id"]
    base = small_project(master={"normalize": False})
    base["tracks"][0]["clips"] = [
        {"id": "a1", "kind": "audio", "asset": asset, "start": 0, "length": 4, "fade_in": 2, "fade_curve": "x"}
    ]
    linear = engine.render(parse_project(base))
    base["tracks"][0]["clips"][0]["fade_curve"] = "x*x"  # slower start
    squared = engine.render(parse_project(base))
    rate = linear.sample_rate
    probe = slice(int(0.4 * rate), int(0.6 * rate))
    assert np.abs(squared.stereo[probe, 0]).max() < np.abs(linear.stereo[probe, 0]).max()


def test_bad_fade_formula_is_reported(tmp_path, monkeypatch):
    from mathmusic import assets

    monkeypatch.setenv("MATHMUSIC_HOME", str(tmp_path))
    asset = assets.import_audio(wav_bytes(seconds=1.0), "tone.wav")["id"]
    data = small_project()
    data["tracks"][0]["clips"] = [
        {"id": "a1", "kind": "audio", "asset": asset, "start": 0, "length": 2, "fade_in": 1, "fade_curve": "open('x')"}
    ]
    with pytest.raises(ProjectError):
        parse_project(data)  # rejected by the parser, as any unsafe formula is


def test_swing_delays_every_second_step_and_keeps_the_grid_closed():
    from mathmusic.composer import NoteEvent
    from mathmusic.engine import _swing

    steps = [NoteEvent(start=i * 1.0, duration=1.0, pitch=60) for i in range(4)]
    swung = _swing(steps, 0.25)
    assert [s.start for s in swung] == [0.0, 1.25, 2.0, 3.25]
    assert swung[1].start + swung[1].duration == pytest.approx(2.0)  # still ends where the next begins
    assert swung[0] == steps[0] and swung[2] == steps[2]


def test_swing_zero_is_a_straight_grid():
    from mathmusic.composer import NoteEvent
    from mathmusic.engine import _swing

    steps = [NoteEvent(start=i * 0.5, duration=0.5, pitch=60) for i in range(6)]
    assert _swing(steps, 0.0) == steps


def test_send_routes_a_track_into_a_bus_as_well_as_the_master():
    """A tone sent to a bus with level 1 and the bus at 0 dB adds about as much as the direct path."""
    base = small_project(master={"normalize": False})
    track = base["tracks"][0]
    track.update(sound="sine", volume_db=0.0, pan=0.0)
    track["clips"][0].update(expression="0", notes=1, length=4, octaves=1, y_min=0, y_max=1)
    no_bus = engine.render(parse_project(base), sample_rate=SR)

    with_bus = small_project(master={"normalize": False}, tracks=[
        {**track, "sends": [{"bus": "b1", "level": 1.0}]},
        {"id": "b1", "name": "Reverb return", "bus": True, "volume_db": -60.0, "clips": []},
    ])
    routed = engine.render(parse_project(with_bus), sample_rate=SR)
    # the bus is at the -60 dB floor, so its copy adds only about a thousandth
    assert np.abs(routed.stereo - no_bus.stereo).max() < 0.002

    loud_bus = small_project(master={"normalize": False}, tracks=[
        {**track, "sends": [{"bus": "b1", "level": 1.0}]},
        {"id": "b1", "name": "Return", "bus": True, "volume_db": 0.0, "clips": []},
    ])
    doubled = engine.render(parse_project(loud_bus), sample_rate=SR)
    # the direct path plus an equal bus copy: the mix doubles
    assert np.abs(doubled.stereo).max() == pytest.approx(2 * np.abs(no_bus.stereo).max(), rel=0.02)


def test_bus_effects_run_on_the_sent_signal():
    base = small_project(master={"normalize": False}, tracks=[
        {"id": "t1", "sound": "sine", "volume_db": 0.0, "sends": [{"bus": "b1", "level": 1.0}],
         "clips": [{"id": "c1", "expression": "0", "notes": 1, "length": 4, "octaves": 1, "y_min": 0, "y_max": 1}]},
        {"id": "b1", "bus": True, "volume_db": 0.0, "clips": [],
         "effects": [{"type": "lowpass", "params": {"cutoff": 30}}]},
    ])
    result = engine.render(parse_project(base), sample_rate=SR)
    direct = engine.render(parse_project({**base, "tracks": [{**base["tracks"][0], "sends": []}]}), sample_rate=SR)
    # a 30 Hz lowpass removes the 440 Hz send, so the mix is the direct path plus almost nothing.
    # Without the bus effect the send would double the peak (0.21 -> 0.42); with it the peak stays near 0.21.
    assert np.abs(result.stereo).max() == pytest.approx(np.abs(direct.stereo).max(), rel=0.02)


def test_bus_rules_are_enforced():
    with pytest.raises(ProjectError, match="not a bus"):
        parse_project(small_project(tracks=[{"id": "t1", "sends": [{"bus": "t2"}]}, {"id": "t2", "clips": []}]))
    with pytest.raises(ProjectError, match="buses hold no clips"):
        parse_project(small_project(tracks=[{"id": "b1", "bus": True, "clips": [{"id": "c1"}]}]))
    with pytest.raises(ProjectError, match="cannot send"):
        parse_project(small_project(tracks=[{"id": "b1", "bus": True, "clips": [], "sends": [{"bus": "b1"}]}]))
    with pytest.raises(ProjectError, match="twice"):
        parse_project(small_project(tracks=[{"id": "b1", "bus": True, "clips": []},
            {"id": "t1", "clips": [], "sends": [{"bus": "b1"}, {"bus": "b1"}]}]))


def test_track_rows_keep_project_order_with_buses_in_between():
    data = small_project(tracks=[
        {"id": "t1", "sound": "sine", "sends": [{"bus": "b1", "level": 0.5}],
         "clips": [{"id": "c1", "expression": "x", "notes": 2, "length": 2, "octaves": 1}]},
        {"id": "b1", "name": "Return", "bus": True, "clips": []},
        {"id": "t2", "sound": "square", "clips": [{"id": "c2", "expression": "x", "notes": 2, "length": 2, "octaves": 1}]},
    ])
    result = engine.render(parse_project(data), sample_rate=SR)
    assert [t["id"] for t in result.tracks] == ["t1", "b1", "t2"]
    assert result.tracks[1].get("bus") is True


def test_stems_are_one_wav_per_clip_track_and_skip_buses(tmp_path):
    import wave

    from mathmusic.cli import main

    data = small_project(tracks=[
        {"id": "t1", "name": "Lead line", "sound": "sine", "sends": [{"bus": "b1", "level": 0.5}],
         "clips": [{"id": "c1", "expression": "x", "notes": 4, "length": 4, "octaves": 1}]},
        {"id": "b1", "name": "Return", "bus": True, "clips": []},
        {"id": "t2", "name": "Bass", "sound": "square", "mute": True,
         "clips": [{"id": "c2", "expression": "x", "notes": 4, "length": 4, "octaves": 1}]},
        {"id": "t3", "name": "Pad", "sound": "organ",
         "clips": [{"id": "c3", "expression": "sin(x)", "notes": 4, "length": 4, "octaves": 1}]},
    ])
    path = tmp_path / "song.json"
    path.write_text(json.dumps(data))
    assert main(["render", str(path), "--stems", str(tmp_path / "stems")]) == 0
    names = sorted(p.name for p in (tmp_path / "stems").iterdir())
    assert names == ["Lead-line.wav", "Pad.wav"]  # the muted bass and the bus are not stems
    with wave.open(str(tmp_path / "stems" / "Pad.wav")) as w:
        assert w.getnchannels() == 2 and w.getframerate() == 44100


def test_stems_match_the_mix_when_there_is_one_track():
    data = small_project()
    project = parse_project(data)
    stems = engine.render_stems(project, sample_rate=SR)
    mix = engine.render(project, sample_rate=SR)
    # the mix adds normalisation and master effects; with neither, one track's stem equals the mix
    data["master"] = {"normalize": False}
    project = parse_project(data)
    stems = engine.render_stems(project, sample_rate=SR)
    mix = engine.render(project, sample_rate=SR)
    assert np.abs(stems["t1"] - mix.stereo).max() < 1e-5


# ---------------------------------------------------------------- robustness


def test_boolean_fields_reject_non_booleans():
    with pytest.raises(ProjectError, match="true or false"):
        parse_project(small_project(tracks=[{"id": "t1", "clips": [], "mute": "false"}]))
    with pytest.raises(ProjectError, match="true or false"):
        parse_project(small_project(tracks=[{"id": "t1", "clips": [], "solo": 0}]))
    with pytest.raises(ProjectError, match="true or false"):
        parse_project(small_project(master={"normalize": "false"}))
    with pytest.raises(ProjectError, match="true or false"):
        parse_project(small_project(tracks=[{"id": "t1", "clips": [], "bus": "yes"}]))
    with pytest.raises(ProjectError, match="true or false"):
        parse_project(small_project(tracks=[{"id": "t1", "clips": [], "effects": [{"type": "lowpass", "bypass": "no"}]}]))


def test_non_finite_fade_curve_is_reported_and_audio_stays_finite(tmp_path, monkeypatch):
    from mathmusic import assets

    monkeypatch.setenv("MATHMUSIC_HOME", str(tmp_path))
    asset = assets.import_audio(wav_bytes(seconds=1.0), "tone.wav")["id"]
    data = small_project(master={"normalize": False})
    data["tracks"][0]["clips"] = [
        {"id": "a1", "kind": "audio", "asset": asset, "start": 0, "length": 2, "fade_in": 1.0, "fade_curve": "sqrt(x-0.2)"}
    ]
    result = engine.render(parse_project(data))
    assert np.isfinite(result.stereo).all()
    assert any(problem.get("field") == "fade_curve" for problem in result.errors)


def test_peaks_never_return_non_finite():
    assert engine.peaks(np.array([[float("nan")], [float("inf")]]), 1) == [0.0, 0.0]


def test_bus_pan_is_applied():
    def render_pan(pan):
        data = small_project(master={"normalize": False}, tracks=[
            {"id": "t1", "sound": "sine", "volume_db": 0.0, "sends": [{"bus": "b1", "level": 1.0}],
             "clips": [{"id": "c1", "expression": "0", "notes": 1, "length": 4, "octaves": 1, "y_min": 0, "y_max": 1}]},
            {"id": "b1", "bus": True, "pan": pan, "volume_db": 0.0, "clips": []},
        ])
        result = engine.render(parse_project(data), sample_rate=SR)
        return float(np.abs(result.stereo[:, 0]).max()), float(np.abs(result.stereo[:, 1]).max())

    left_dominant = render_pan(-1.0)
    right_dominant = render_pan(1.0)
    assert left_dominant[0] > left_dominant[1]
    assert right_dominant[1] > right_dominant[0]


def test_bus_gain_automation_is_applied():
    def render(automation):
        data = small_project(master={"normalize": False}, tracks=[
            {"id": "t1", "sound": "sine", "sends": [{"bus": "b1", "level": 1.0}],
             "clips": [{"id": "c1", "expression": "0", "notes": 1, "length": 4, "octaves": 1, "y_min": 0, "y_max": 1}]},
            {"id": "b1", "bus": True, "volume_db": 0.0, "automation": automation, "clips": []},
        ])
        return float(np.abs(engine.render(parse_project(data), sample_rate=SR).stereo).max())

    assert render({"gain": "0"}) < render({})  # a bus automated to silence only leaves the direct path


def test_api_type_errors_are_400(api):
    status, body = api("/api/render", "POST", {"options": {"samples": None}, "expressions": [{"src": "x"}]})
    assert status == 400 and "samples" in body["error"]
    status, body = api("/api/plot", "POST", {"formula": "x", "points": None})
    assert status == 400
    status, body = api("/api/render", "POST", {"expressions": [5, {"src": "x", "waveform": 7}]})
    assert status == 200
    assert [problem["index"] for problem in body["errors"]] == [0, 1]


def test_mp3_failure_is_reported_as_json(api, monkeypatch):
    import mathmusic.server as server

    def boom(*args, **kwargs):
        raise RuntimeError("ffmpeg is needed for MP3 output")

    monkeypatch.setattr(server, "encode_mp3", boom)
    status, body = api("/api/project/render", "POST", {"project": small_project()})
    url = body["audio"]["url"].replace(".wav", ".mp3")
    status, body = api(url)
    assert status == 502 and "ffmpeg" in body["error"]


def test_cli_rejects_out_of_range_options(tmp_path):
    from mathmusic.cli import main

    for argv in (
        ["sin(x)", "--bpm", "0"],
        ["sin(x)", "--bpm", "inf"],
        ["sin(x)", "--samples", "1"],
        ["sin(x)", "--octaves", "9"],
        ["sin(x)", "--step", "0"],
        ["sin(x)", "--step", "inf"],
        ["sin(x)", "--start", "nan", "--end", "2"],
        ["sin(x)", "--start", "0", "--end", "inf"],
        ["sin(x)", "--start", "2", "--end", "1"],
    ):
        assert main([*argv, "-o", str(tmp_path / "x.wav")]) == 2
    assert not (tmp_path / "x.wav").exists()
