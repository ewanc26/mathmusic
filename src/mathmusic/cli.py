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

from mathmusic.composer import Options, build_voices
from mathmusic.expr import ExpressionError
from mathmusic.scales import SCALES
from mathmusic.synth import SAMPLE_RATE, encode_mp3, mix, write_wav


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mathmusic",
        description="Turn mathematical curves into music. Each expression is one voice; "
        "x runs left to right in time and y sets the pitch.",
    )
    parser.add_argument("expressions", nargs="+", help='e.g. "sin(x)" "x^2/8" "5*sinc(x)"')
    parser.add_argument("--start", type=float, default=0.0, help="first x value (default 0)")
    parser.add_argument("--end", type=float, default=4 * pi, help="last x value (default 4*pi)")
    parser.add_argument("--samples", type=int, default=96, help="notes per voice (default 96)")
    parser.add_argument("--scale", choices=sorted(SCALES), default="pentatonic")
    parser.add_argument("--root", type=int, default=60, help="root as a MIDI note (60 = C4)")
    parser.add_argument("--octaves", type=int, default=2, help="pitch range in octaves (default 2)")
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
    )

    try:
        voices = build_voices(args.expressions, opts)
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
