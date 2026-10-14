import numpy as np
import pytest

from mathmusic.composer import Options, build_voices, curve_to_notes
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


def test_undefined_points_are_nan_or_inf_not_errors():
    values = Expression("log(x)").evaluate(np.array([-1.0, 0.0, 1.0]))
    assert not np.isfinite(values[0]) and not np.isfinite(values[1])
    assert values[2] == pytest.approx(0.0)


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


def test_render_project_rejects_bad_options():
    from mathmusic.server import render_project

    with pytest.raises(ValueError):
        render_project({"expressions": [{"src": "x"}], "options": {"start": 3, "end": 1}})
    with pytest.raises(ValueError):
        render_project({"expressions": [{"src": "x"}], "options": {"scale": "nope"}})
