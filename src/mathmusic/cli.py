"""Command line entry point.

    mathmusic serve                      open the graphing UI in a browser
    mathmusic "sin(x)" "x^2/8" -o a.mp3  render expressions without the UI
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from math import pi
from pathlib import Path

import numpy as np

from mathmusic.composer import Options, build_voices
from mathmusic.expr import ExpressionError
from mathmusic.scales import SCALES
from mathmusic.synth import SAMPLE_RATE, encode_mp3, mix, write_wav


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mathmusic",
        description="Sketch mode: turn mathematical curves into music. Each expression is one voice; "
        "x runs left to right in time and y sets the pitch.",
        epilog="other commands:\n"
        "  mathmusic serve [--port N]                     open the DAW in your browser\n"
        "  mathmusic render PROJECT.json [-o OUT]         render a saved project to .mp3, .wav or .mid\n"
        "  mathmusic instruments                          list waveforms and instruments with their formulas",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("expressions", nargs="+", help='e.g. "sin(x)" "x^2/8" "5*sinc(x)"')
    parser.add_argument("--start", type=float, default=0.0, help="first x value (default 0)")
    parser.add_argument("--end", type=float, default=4 * pi, help="last x value (default 4*pi)")
    parser.add_argument("--samples", type=int, default=96, help="notes per voice (default 96)")
    parser.add_argument("--scale", choices=sorted(SCALES), default="pentatonic")
    parser.add_argument("--root", type=int, default=60, help="root as a MIDI note (60 = C4)")
    parser.add_argument("--octaves", type=int, default=2, help="pitch range in octaves (default 2)")
    parser.add_argument(
        "--pitch-range",
        choices=["shared", "per-voice"],
        default="shared",
        help="shared: all voices use one pitch range (keeps relative height); per-voice: each curve fills the range",
    )
    parser.add_argument(
        "--wave",
        help="sound for every voice: a waveform (sine, triangle, saw, square, pulse), an instrument "
        "(see `mathmusic instruments`), or a formula in x, e.g. \"sin(2*pi*x) + 0.3*sin(6*pi*x)\"",
    )
    parser.add_argument("--bpm", type=float, default=120.0)
    parser.add_argument("--step", type=float, default=0.5, help="beats per sample (default 0.5)")
    parser.add_argument(
        "--rhythm",
        choices=["uniform", "slope"],
        default="uniform",
        help="slope: steep parts of the curve get shorter notes",
    )
    parser.add_argument("-o", "--output", type=Path, default=Path("mathmusic.mp3"), help="output .mp3 or .wav")
    parser.add_argument("--plot", action="store_true", help="also save a PNG of the curves next to the audio")
    parser.add_argument("--publish", action="store_true", help="upload the track to plyr.fm (needs PLYR_TOKEN)")
    parser.add_argument("--title", help="track title (default: the expressions)")
    parser.add_argument("--album", help="album name on plyr.fm")
    parser.add_argument("--tags", help="comma-separated tags for plyr.fm")
    parser.add_argument("--description", help="liner notes for plyr.fm")
    return parser


def render_main(argv: list[str]) -> int:
    import json

    from mathmusic import engine
    from mathmusic.project import ProjectError, parse_project

    parser = argparse.ArgumentParser(prog="mathmusic render", description="Render a saved DAW project to audio.")
    parser.add_argument("project", type=Path, help="project .json file (saved from the UI)")
    parser.add_argument("-o", "--output", type=Path, help="output .mp3, .wav or .mid (default: .mp3 next to the project)")
    parser.add_argument(
        "--stems",
        type=Path,
        metavar="DIR",
        help="write one WAV per clip track into DIR instead of a mix (track output before the master chain)",
    )
    args = parser.parse_args(argv)

    try:
        project = parse_project(json.loads(args.project.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ProjectError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.stems is not None:
        import re

        from mathmusic.synth import SAMPLE_RATE

        stems = engine.render_stems(project)
        args.stems.mkdir(parents=True, exist_ok=True)
        written = 0
        for track in project.tracks:
            if track.bus or track.id not in stems:
                continue
            audio = stems[track.id]
            if not audio.size or not np.abs(audio).any():
                continue
            safe = re.sub(r"[^A-Za-z0-9_-]+", "-", track.name).strip("-") or track.id
            path = args.stems / f"{safe}.wav"
            write_wav(path, audio, SAMPLE_RATE)
            written += 1
            print(f"wrote {path}")
        if not written:
            print("error: no track is audible to export as a stem", file=sys.stderr)
            return 2
        return 0

    if args.output is not None and args.output.suffix.lower() in (".mid", ".midi"):
        from mathmusic.midi import project_to_midi

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(project_to_midi(project))
        print(f"wrote {args.output} ({len(project.tracks)} track(s), MIDI)")
        return 0
    result = engine.render(project)
    for problem in result.errors:
        place = " ".join(str(problem[k]) for k in ("track", "clip", "field") if problem.get(k))
        print(f"warning: {place}: {problem['error']}", file=sys.stderr)
    if result.stereo.size == 0:
        print("error: the project has no clips to render", file=sys.stderr)
        return 2

    output: Path = args.output or args.project.with_suffix(".mp3")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        wav = write_wav(Path(tmp) / "mix.wav", result.stereo)
        if output.suffix.lower() == ".wav":
            wav.replace(output)
        else:
            encode_mp3(wav, output)
    print(f"wrote {output} ({result.duration:.1f}s, {len(project.tracks)} track(s))")
    return 0


def instruments_main() -> int:
    from mathmusic.waves import describe_all

    catalogue = describe_all()
    print("Waveforms (one period, x = phase in cycles):")
    for wave in catalogue["waveforms"]:
        print(f"  {wave['name']:<10} {wave['formula']}")
    print("\nInstruments (waveform + envelope over the note, x = position in the note):")
    for inst in catalogue["instruments"]:
        print(f"  {inst['name']:<10} {inst['description']}")
        print(f"             wave:     {inst['wave']}")
        print(f"             envelope: {inst['envelope']}")
    return 0


def serve_main(argv: list[str]) -> int:
    from mathmusic.server import serve

    parser = argparse.ArgumentParser(prog="mathmusic serve", description="Open the mathmusic graphing UI.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    args = parser.parse_args(argv)
    serve(port=args.port, open_browser=not args.no_browser)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["serve"]:
        return serve_main(argv[1:])
    if argv[:1] == ["instruments"]:
        return instruments_main()
    if argv[:1] == ["render"]:
        return render_main(argv[1:])

    args = build_parser().parse_args(argv)
    opts = Options(
        start=args.start,
        end=args.end,
        samples=args.samples,
        scale=args.scale,
        root_midi=args.root,
        octaves=args.octaves,
        bpm=args.bpm,
        step_beats=args.step,
        rhythm=args.rhythm,
        pitch_mode=args.pitch_range,
    )

    try:
        waveforms = [args.wave] * len(args.expressions) if args.wave else None
        voices = build_voices(args.expressions, opts, waveforms=waveforms)
    except (ExpressionError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    output: Path = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    stereo = mix(voices, opts.bpm, SAMPLE_RATE)
    if stereo.size == 0:
        print("error: none of the expressions produced any defined points in that range", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory() as tmp:
        wav = write_wav(Path(tmp) / "track.wav", stereo)
        if output.suffix.lower() == ".wav":
            wav.replace(output)
        else:
            encode_mp3(wav, output)
    print(f"wrote {output} ({stereo.shape[0] / SAMPLE_RATE:.1f}s, {len(voices)} voice(s))")

    if args.plot:
        from mathmusic.plot import plot_voices

        png = plot_voices(voices, output.with_suffix(".png"))
        print(f"wrote {png}")

    if args.publish:
        from mathmusic.publish import publish_to_plyr

        title = args.title or " + ".join(args.expressions)
        tags = {t.strip() for t in args.tags.split(",") if t.strip()} if args.tags else None
        try:
            track_id = publish_to_plyr(
                output,
                title,
                album=args.album,
                tags=tags,
                description=args.description,
            )
        except (RuntimeError, ValueError) as exc:
            print(f"publish failed: {exc}", file=sys.stderr)
            return 1
        print(f"published to plyr.fm as track {track_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
