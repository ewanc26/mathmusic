# mathmusic

Turn mathematical curves into music. Each expression is one voice. The curve is read left to right as time, and its height sets the pitch.

## Graphing UI

```bash
mathmusic serve            # opens http://127.0.0.1:8765 in your browser
```

- **Graph:** every expression is plotted live. Scroll to zoom, drag to pan, double-click or "Fit view" to reset. Hover a point to read x, y, the note it plays and its time.
- **Piano roll:** the notes over time, coloured by voice. Click to seek.
- **Transport:** play/pause (or Space), with a playhead on both the graph and the roll. Download the render as WAV or MP3.
- **Expressions:** add, remove, enable or mute each voice, and pick its waveform. Errors show inline.
- **Presets:** Three curves, Damped, Gaussian, Beating.
- **Publish:** uploads the current render to plyr.fm. See below.

The browser sends your expressions to a local server, which uses the same engine as the CLI. What you see is what plays and what gets published. The server only listens on 127.0.0.1.

## Command line

```bash
mathmusic "sin(x)" "x^2/(2*pi*pi) - 0.5" "2*sinc(x-4)" --end 12.566 --bpm 110 --plot -o out/three_curves.mp3
```

## Setup

Needs Python 3.10+ and ffmpeg for MP3 output (`brew install ffmpeg`).

```bash
uv venv .venv && uv pip install --python .venv/bin/python -e ".[plot,publish]"
```

## How curves become notes

- **x** runs from `--start` to `--end` in `--samples` steps. Each step is one note.
- **y** is normalised to the curve's own min/max, then quantised onto `--scale` across `--octaves`.
- `--rhythm uniform` gives every note `--step` beats. `--rhythm slope` gives steep parts shorter notes.
- Undefined points (`log(-1)`, division by zero) become rests.
- Voices get different waveforms and are panned across the stereo field.

Expressions accept `+ - * / ^ %`, `x`, `pi`, `tau`, `e`, and functions such as `sin cos tan exp log sqrt abs floor sinc mod min max clip`. Anything else is rejected before evaluation.

## Publishing to plyr.fm

`--publish` uploads the rendered MP3 to [plyr.fm](https://plyr.fm), which is music on AT Protocol. Create a developer token at plyr.fm/settings#developer and export it. Your account needs an artist profile on plyr.fm.

```bash
export PLYR_TOKEN="your_token"
mathmusic "sin(3*x)*exp(-x/6)" --end 20 --rhythm slope --publish --title "Damped Three" --tags math,generative -o out/damped.mp3
```

Uploads go through the [`plyrfm`](https://pypi.org/project/plyrfm/) SDK (`tracks.upload`). The SDK does not accept cover art, so `--plot` images stay local.

## Tests

```bash
.venv/bin/python -m pytest
```
