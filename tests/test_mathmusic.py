import json

import numpy as np
import pytest

from mathmusic.composer import Options, build_voices, curve_to_notes, curve_to_steps
from mathmusic.expr import Expression, ExpressionError
from mathmusic.scales import pitch_table
from mathmusic.synth import SAMPLE_RATE, mix, write_wav


def test_evaluates_arithmetic_and_functions():
    values = Expression("2*sin(x) + x^2 - 1").evaluate(np.array([0.0, np.pi / 2]))
    assert values[0] == pytest.approx(-1.0)
    assert values[1] == pytest.approx(2 + (np.pi / 2) ** 2 - 1)


def test_constants_are_available():
    assert Expression("pi").evaluate(0.0) == pytest.approx(np.pi)


@pytest.mark.parametrize(
    "source",
    [
        "__import__('os').system('ls')",
        "x.real",
        "x[0]",
        "open('f')",
        "(lambda: 1)()",
        "y + 1",
        "sin",
        "'text'",
    ],
)
def test_rejects_unsafe_or_unknown_input(source):
    with pytest.raises(ExpressionError):
        Expression(source)


def test_compiled_expressions_are_shared_but_failures_are_not_cached():
    from mathmusic.expr import compile_expression

    first = compile_expression("sin(x) + 1")
    assert compile_expression("sin(x) + 1") is first  # rendering loops reuse the parse
    assert np.allclose(first.evaluate(np.array([0.0])), [1.0])
    for _ in range(2):  # a formula that cannot run raises every time, never a stale result
        with pytest.raises(ExpressionError):
            compile_expression("max(x)")


def test_undefined_points_are_nan_or_inf_not_errors():
    values = Expression("log(x)").evaluate(np.array([-1.0, 0.0, 1.0]))
    assert not np.isfinite(values[0]) and not np.isfinite(values[1])
    assert values[2] == pytest.approx(0.0)


def test_division_by_zero_is_an_undefined_point_not_an_error():
    values = Expression("1/(x-1)").evaluate(np.array([0.0, 1.0, 2.0]))
    assert values[0] == pytest.approx(-1.0)
    assert np.isinf(values[1])
    assert Expression("1/0").evaluate(0.0) == np.inf


@pytest.mark.parametrize("source", ["max(x)", "sin(x, 1)", "clip(x, 1)", "mod(x)", "sin(x=1)"])
def test_wrong_argument_count_is_rejected_before_evaluation(source):
    with pytest.raises(ExpressionError, match="argument"):
        Expression(source)


def test_two_argument_functions_evaluate():
    assert Expression("clip(x, 0, 0.5)").evaluate(np.array([-1.0, 0.25, 2.0])).tolist() == [0.0, 0.25, 0.5]
    assert Expression("max(x, 0.5)").evaluate(np.array([0.0, 1.0])).tolist() == [0.5, 1.0]
@pytest.mark.parametrize(
    "source",
    [
        "min(x)",  # whitelisted function called with too few arguments
        "max(x)",
        "mod(x)",
        "sin()",
        "sin(x, 1)",
    ],
)
def test_evaluation_failures_raise_expression_error(source):
    # a formula that parses but cannot run must raise ExpressionError, not a
    # TypeError that would escape the engine's error handling
    with pytest.raises(ExpressionError):
        Expression(source).evaluate(np.array([0.0, 0.5, 1.0]))


@pytest.mark.parametrize("source", ["1/0", "1%0", "1/(x-0.5)"])
def test_division_by_zero_becomes_a_rest(source):
    # the README: division by zero is undefined and becomes a rest, like log(-1)
    values = Expression(source).evaluate(np.array([0.5, 1.0]))
    assert not np.isfinite(values[0])  # undefined at x = 0.5 for every form above


def test_pitch_table_covers_octaves_and_ends_on_tonic():
    pitches = pitch_table("major", 60, 1)
    assert pitches == [60, 62, 64, 65, 67, 69, 71, 72]


def test_curve_maps_lowest_and_highest_values_to_range_ends():
    opts = Options(scale="chromatic", octaves=1, root_midi=60)
    notes = curve_to_notes(np.array([0.0, 0.5, 1.0]), opts)
    assert [n.pitch for n in notes] == [60, 66, 72]


def test_non_finite_samples_become_rests():
    opts = Options(scale="chromatic", octaves=1, step_beats=1.0)
    notes = curve_to_notes(np.array([0.0, np.nan, 1.0]), opts)
    assert len(notes) == 2
    assert notes[1].start == pytest.approx(2.0)  # rest still advances time


def test_slope_rhythm_shortens_steep_notes():
    opts = Options(rhythm="slope", step_beats=1.0)
    notes = curve_to_notes(np.array([0.0, 0.0, 0.0, 10.0, 10.0, 10.0]), opts)
    durations = [n.duration for n in notes]
    assert min(durations) < max(durations)
    assert max(durations) == pytest.approx(1.0)


def test_build_voices_and_mix_produce_stereo_audio(tmp_path):
    voices = build_voices(["sin(x)", "x/4"], Options(samples=32))
    assert len(voices) == 2
    assert voices[0].pan < 0 < voices[1].pan
    stereo = mix(voices, bpm=120)
    assert stereo.shape[1] == 2 and stereo.shape[0] > SAMPLE_RATE
    assert np.abs(stereo).max() <= 0.9

    path = write_wav(tmp_path / "t.wav", stereo)
    assert path.stat().st_size > 1000


def test_invalid_range_is_rejected():
    with pytest.raises(ValueError):
        build_voices(["x"], Options(start=2, end=1))


def test_parse_note_names():
    from mathmusic.scales import parse_note

    assert parse_note("C4") == 60
    assert parse_note("A4") == 69
    assert parse_note("F#3") == 54
    assert parse_note("Bb2") == 46
    with pytest.raises(ValueError):
        parse_note("H4")


def test_steps_keep_rests_and_timing():
    from mathmusic.composer import curve_to_steps

    steps = curve_to_steps(np.array([0.0, np.nan, 1.0]), Options(step_beats=1.0, octaves=1))
    assert [s.pitch is None for s in steps] == [False, True, False]
    assert [s.start for s in steps] == [0.0, 1.0, 2.0]


def test_per_voice_waveform_override():
    voices = build_voices(["x", "x"], Options(samples=4), waveforms=["square", None])
    assert voices[0].waveform == "square"
    assert voices[1].waveform == "triangle"
    with pytest.raises(ValueError):
        build_voices(["x"], Options(samples=4), waveforms=["buzz"])


def test_render_project_returns_graph_data_and_audio(tmp_path):
    from mathmusic.server import render_project

    payload = {
        "expressions": [
            {"src": "sin(x)", "waveform": None, "enabled": True},
            {"src": "log(x-2)", "waveform": "saw", "enabled": True},
            {"src": "x +", "enabled": True},
            {"src": "x", "enabled": False},
        ],
        "options": {"start": 0, "end": 6, "samples": 20, "scale": "major", "root": "C4", "octaves": 1, "bpm": 120, "step": 0.5, "rhythm": "uniform"},
    }
    result = render_project(payload)
    assert [v["index"] for v in result["voices"]] == [0, 1]
    assert result["voices"][1]["waveform"] == "saw"
    assert result["errors"][0]["index"] == 2
    assert result["audio"]["url"].endswith(".wav")
    # undefined points are null in JSON, never NaN
    assert any(s["y"] is None for s in result["voices"][1]["samples"])
    assert result["duration"] > 0


def test_render_project_reports_a_formula_that_cannot_run(tmp_path):
    from mathmusic.server import render_project

    # min(x) parses but calls minimum() with too few arguments: report it against
    # its index (and still render the other expression), never raise
    payload = {
        "expressions": [
            {"src": "min(x)", "enabled": True},
            {"src": "sin(x)", "enabled": True},
        ],
        "options": {"start": 0, "end": 6, "samples": 20, "octaves": 1},
    }
    result = render_project(payload)
    assert len(result["errors"]) == 1
    assert result["errors"][0]["index"] == 0
    assert "min" in result["errors"][0]["error"]
    assert [v["index"] for v in result["voices"]] == [1]


def test_render_project_rejects_bad_options():
    from mathmusic.server import render_project

    with pytest.raises(ValueError):
        render_project({"expressions": [{"src": "x"}], "options": {"start": 3, "end": 1}})
    with pytest.raises(ValueError):
        render_project({"expressions": [{"src": "x"}], "options": {"scale": "nope"}})


@pytest.mark.parametrize("options", [{"end": "nan"}, {"start": "-inf"}, {"end": "inf"}, {"end": "abc"}])
def test_render_project_rejects_non_finite_range(options):
    from mathmusic.server import render_project

    with pytest.raises(ValueError):
        render_project({"expressions": [{"src": "x"}], "options": options})


def test_slope_rhythm_survives_undefined_samples():
    opts = Options(rhythm="slope", step_beats=1.0, octaves=1)
    steps = curve_to_steps(np.array([0.0, 1.0, 2.0, np.nan, 4.0, 4.0, 4.0, 4.0]), opts)
    durations = [s.duration for s in steps]
    # the flat tail keeps full-length notes, so the rhythm is not uniform
    assert durations[-1] == pytest.approx(1.0)
    assert min(durations) < max(durations)


def test_slope_rhythm_on_straight_line_is_steady_not_all_shortest():
    opts = Options(rhythm="slope", step_beats=1.0, octaves=1)
    steps = curve_to_steps(np.linspace(0, 10, 11), opts)
    durations = {round(s.duration, 6) for s in steps}
    assert len(durations) == 1
    assert 0.25 < durations.pop() < 1.0


@pytest.fixture
def http_server():
    import threading

    from mathmusic.server import make_server

    server = make_server(0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    yield f"http://127.0.0.1:{port}", server.allowed_hosts
    server.shutdown()
    server.server_close()


def _request(url, *, method="GET", headers=None, body=None):
    import json as _json
    import urllib.error
    import urllib.request

    data = None if body is None else _json.dumps(body).encode()
    req = urllib.request.Request(url, method=method, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return res.status, res.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_api_status_is_served_to_loopback(http_server):
    base, _ = http_server
    status, body = _request(f"{base}/api/status")
    assert status == 200
    assert "ffmpeg" in json.loads(body)


def test_rejects_foreign_host_header(http_server):
    base, _ = http_server
    status, _ = _request(f"{base}/api/status", headers={"Host": "evil.example"})
    assert status == 403


def test_rejects_cross_origin_post(http_server):
    base, _ = http_server
    status, _ = _request(
        f"{base}/api/render",
        method="POST",
        headers={"Content-Type": "application/json", "Origin": "https://evil.example"},
        body={"expressions": [{"src": "x"}]},
    )
    assert status == 403


def test_rejects_non_json_post(http_server):
    base, _ = http_server
    status, _ = _request(
        f"{base}/api/render",
        method="POST",
        headers={"Content-Type": "text/plain"},
        body={"expressions": [{"src": "x"}]},
    )
    assert status == 415


def test_same_origin_json_render_succeeds(http_server):
    base, _ = http_server
    host = base.removeprefix("http://")
    status, body = _request(
        f"{base}/api/render",
        method="POST",
        headers={"Content-Type": "application/json", "Origin": f"http://{host}"},
        body={"expressions": [{"src": "sin(x)"}], "options": {"samples": 8}},
    )
    assert status == 200
    assert json.loads(body)["voices"][0]["expression"] == "sin(x)"


def test_voice_limit_is_enforced():
    from mathmusic.server import MAX_VOICES, render_project

    payload = {"expressions": [{"src": "x"} for _ in range(MAX_VOICES + 1)], "options": {"samples": 4}}
    with pytest.raises(ValueError):
        render_project(payload)


def test_shared_pitch_range_keeps_relative_amplitude():
    opts = Options(samples=64, scale="chromatic", octaves=3, pitch_mode="shared")
    small, large = build_voices(["sin(x)", "10*sin(x)"], opts)
    small_pitches = [s.pitch for s in small.notes]
    large_pitches = [s.pitch for s in large.notes]
    assert max(large_pitches) - min(large_pitches) > 2 * (max(small_pitches) - min(small_pitches))


def test_per_voice_pitch_range_stretches_each_curve():
    opts = Options(samples=64, scale="chromatic", octaves=3, pitch_mode="per-voice")
    small, large = build_voices(["sin(x)", "10*sin(x)"], opts)
    small_span = max(s.pitch for s in small.notes) - min(s.pitch for s in small.notes)
    large_span = max(s.pitch for s in large.notes) - min(s.pitch for s in large.notes)
    assert small_span == large_span


def test_invert_flips_pitch_direction():
    opts = Options(samples=16, scale="chromatic", octaves=2)
    normal, flipped = build_voices(["x", "x"], opts, inverts=[False, True])
    assert normal.notes[0].pitch < normal.notes[-1].pitch
    assert flipped.notes[0].pitch > flipped.notes[-1].pitch
    assert flipped.inverted and not normal.inverted


def test_invert_list_must_match_sources():
    with pytest.raises(ValueError):
        build_voices(["x", "x"], Options(samples=4), inverts=[True])


def test_unknown_pitch_mode_is_rejected():
    with pytest.raises(ValueError):
        build_voices(["x"], Options(samples=4, pitch_mode="log"))


def test_render_project_passes_invert_and_pitch_mode():
    from mathmusic.server import render_project

    result = render_project(
        {
            "expressions": [{"src": "x", "invert": True}, {"src": "x"}],
            "options": {"samples": 8, "octaves": 1, "scale": "chromatic", "pitch_mode": "per-voice"},
        }
    )
    assert result["voices"][0]["inverted"] is True
    assert result["voices"][1]["inverted"] is False
    with pytest.raises(ValueError):
        render_project({"expressions": [{"src": "x"}], "options": {"pitch_mode": "bogus"}})


def test_builtin_wavetables_have_expected_shapes():
    from mathmusic.waves import BUILTIN_WAVES, wavetable

    sine = wavetable(BUILTIN_WAVES["sine"])
    assert sine[len(sine) // 4] == pytest.approx(1.0, abs=1e-3)  # quarter cycle is the peak
    square = wavetable(BUILTIN_WAVES["square"])
    assert square[len(square) // 4] == pytest.approx(1.0)
    assert square[3 * len(square) // 4] == pytest.approx(-1.0)
    pulse = wavetable(BUILTIN_WAVES["pulse"])
    assert pulse[len(pulse) // 8] == pytest.approx(1.0)  # inside the 25% duty window
    assert pulse[len(pulse) // 2] == pytest.approx(-1.0)


def test_every_instrument_preset_is_a_valid_formula_pair():
    from mathmusic.waves import INSTRUMENTS, envelope_values, resolve, wavetable

    positions = np.linspace(0, 1, 50)
    for name, inst in INSTRUMENTS.items():
        table = wavetable(inst.wave)
        assert np.isfinite(table).all() and np.abs(table).max() == pytest.approx(1.0), name
        gain = envelope_values(inst.envelope, positions)
        assert np.isfinite(gain).all() and gain.min() >= -1.0001 and gain.max() <= 1.0001, name
        assert resolve(name).instrument == name


def test_custom_formula_is_accepted_and_bad_ones_rejected():
    from mathmusic.waves import resolve

    good = "sin(2*pi*x) + 0.5*sin(4*pi*x)"
    assert resolve(good).wave == good
    for bad in ["__import__('os')", "sin(2*pi*x", "1/x", "0*x", "x" * 301, "y"]:
        with pytest.raises(ValueError):
            resolve(bad)


def test_voice_takes_instrument_formulas():
    voice = build_voices(["x"], Options(samples=4, octaves=1), waveforms=["pluck"])[0]
    assert voice.instrument == "pluck"
    assert voice.envelope_formula == "exp(-6*x)"
    assert voice.waveform == "pluck"


def test_pluck_envelope_decays_within_each_note():
    from mathmusic.synth import render_voice

    voice = build_voices(["1"], Options(samples=2, octaves=1, step_beats=1.0), waveforms=["pluck"])[0]
    sample_rate = 8000
    buffer = render_voice(voice, seconds_per_beat=1.0, sample_rate=sample_rate)  # one second per note
    onset = np.abs(buffer[: sample_rate // 10]).mean()
    tail = np.abs(buffer[int(0.8 * sample_rate) : int(0.9 * sample_rate)]).mean()
    assert onset > 5 * tail


def test_server_reports_bad_sound_per_expression(http_server):
    from mathmusic.server import render_project

    result = render_project(
        {
            "expressions": [{"src": "x", "waveform": "bell"}, {"src": "x", "waveform": "__import__('os')"}],
            "options": {"samples": 4, "octaves": 1},
        }
    )
    assert result["voices"][0]["instrument"] == "bell"
    assert result["errors"][0]["index"] == 1


@pytest.mark.parametrize("length", ["abc", "-1"])
def test_malformed_content_length_is_a_400_not_a_crash(http_server, length):
    base, _ = http_server
    status, body = _request(
        f"{base}/api/project/render",
        method="POST",
        headers={"Content-Type": "application/json", "Content-Length": length},
    )
    assert status == 400
    assert "Content-Length" in json.loads(body)["error"]
def test_plot_rejects_infinite_point_count():
    from mathmusic.server import plot_formula

    with pytest.raises(ValueError, match="must be numbers"):
        plot_formula({"formula": "x", "points": float("inf")})
@pytest.mark.parametrize("expressions", [-1, 2.5, "sin(x)", {"src": "x"}])
def test_render_project_rejects_non_list_expressions(expressions):
    from mathmusic.server import render_project

    with pytest.raises(ValueError, match="must be a list"):
        render_project({"expressions": expressions})
@pytest.mark.parametrize("kind", [["lowpass"], {"type": "delay"}, 3, None])
def test_effect_type_must_be_a_known_name(kind):
    from mathmusic.project import ProjectError, parse_project

    data = {"tracks": [{"id": "t1", "sound": "sine", "effects": [{"type": kind}], "clips": []}]}
    with pytest.raises(ProjectError, match="type must be one of"):
        parse_project(data)


def test_instrument_catalogue_endpoint(http_server):
    base, _ = http_server
    status, body = _request(f"{base}/api/instruments")
    assert status == 200
    names = {inst["name"] for inst in json.loads(body)["instruments"]}
    assert {"organ", "clarinet", "brass", "pluck", "bell", "fm", "hollow", "reed"} <= names


def test_clarinet_has_only_odd_harmonics():
    from mathmusic.waves import INSTRUMENTS, wavetable

    table = wavetable(INSTRUMENTS["clarinet"].wave)[:-1]  # drop the repeated endpoint
    spectrum = np.abs(np.fft.rfft(table))
    assert spectrum[1] > 0.5  # fundamental
    assert spectrum[2] < 1e-6 and spectrum[4] < 1e-6  # even harmonics absent
    assert spectrum[3] > 0.1  # third harmonic present


def _project_with(**changes):
    """A minimal valid project, with the given top-level changes applied."""
    data = {"tracks": [{"id": "t1", "sound": "sine", "clips": [
        {"id": "c1", "start": 0, "length": 4, "notes": 4, "expression": "x"}]}]}
    data.update(changes)
    return data


@pytest.mark.parametrize("changes, message", [
    ({"tracks": [{"id": "t1", "volume_db": "loud", "clips": []}]}, "must be a number"),
    ({"beats_per_bar": 2.5}, "must be a whole number"),
    ({"tracks": [{"id": "t1", "name": 5, "clips": []}]}, "must be text"),
    ({"tracks": [{"id": "t1", "name": "a" * 500, "clips": []}]}, "is longer than"),
    ({"tracks": "not a list"}, "must be a list"),
    ({"tracks": [{"id": "t1", "effects": ["delay"], "clips": []}]}, "entries must be objects"),
    ({"tracks": [{"id": "t1", "effects": [{"type": "delay", "params": [1]}], "clips": []}]}, "params must be an object"),
    ({"tracks": [{"id": "t1", "clips": [{"id": "c1", "start": 0, "length": 4, "notes": 4, "expression": "x", "kind": "video"}]}]}, "kind must be one of"),
    ({"tracks": [{"id": "t1", "clips": [{"id": "c1", "start": 0, "length": 4, "notes": 4, "expression": "x", "y_min": 1, "y_max": 0}]}]}, "y_max must be greater than y_min"),
    ({"tracks": [{"id": "t1", "clips": [{"id": "c1", "start": 2000, "length": 100, "notes": 4, "expression": "x"}]}]}, "ends after beat"),
    ({"tracks": [{"id": "t1", "automation": "x", "clips": []}]}, "automation must be an object"),
    ({"tracks": [{"id": "t1", "sends": [{"bus": 5}], "clips": []}]}, "must be a track id"),
    ([], "project must be an object"),
    ({"master": "loud"}, "master must be an object"),
    ({"loop_start": 10, "loop_end": 5}, "loop_end must be greater than loop_start"),
])
def test_project_validation_names_the_bad_field(changes, message):
    from mathmusic.project import ProjectError, parse_project

    data = changes if isinstance(changes, list) else _project_with(**changes)
    with pytest.raises(ProjectError, match=message):
        parse_project(data)


def test_project_limits_are_enforced_for_notes_and_length():
    from mathmusic.project import LIMITS, ProjectError, parse_project

    clip = {"id": "c1", "start": 0, "length": 4, "notes": LIMITS["notes_per_clip"], "expression": "x"}
    tracks = [{"id": f"t{i}", "clips": [dict(clip, id=f"c{i}")]} for i in range(9)]  # 9 * 1024 > 8000 notes
    with pytest.raises(ProjectError, match="the limit is"):
        parse_project({"tracks": tracks})
