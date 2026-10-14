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

The browser sends your expressions to a local server, which uses the same engine as the CLI. What you see is what plays and what gets published. The server only listens on 127.0.0.1, and it refuses requests whose Host or Origin is not the local address, so other websites cannot use it to render or publish.

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
- **y** is quantised onto `--scale` across `--octaves`. By default (`--pitch-range shared`) all voices share one range, so a curve with bigger values sounds higher and the relative amplitudes survive. `--pitch-range per-voice` stretches each curve to fill the range, which shows its shape but hides amplitude.
- In the UI, **invert** flips a voice's direction, so high values sound low.
- `--rhythm uniform` gives every note `--step` beats. `--rhythm slope` gives steep parts shorter notes.
- Undefined points (`log(-1)`, division by zero) become rests.
- Voices get different waveforms and are panned across the stereo field.

Expressions accept `+ - * / ^ %`, `x`, `pi`, `tau`, `e`, and functions such as `sin cos tan exp log sqrt abs floor sinc mod min max clip`. Anything else is rejected before evaluation.

## Sounds: waveforms, instruments and formulas

Every sound is a mathematical formula, so you can read it and change it.

- A **waveform** is one period of a wave, written in `x`, where `x` is the phase in cycles (0 to 1). `sin(2*pi*x)` is a sine. Built in: `sine`, `triangle`, `saw`, `square`, `pulse` (25% duty).
- An **instrument** pairs a waveform with an **envelope**, a formula in `x` where `x` is the position in the note (0 at the start, 1 at the end). Built in: `organ`, `clarinet`, `brass`, `pluck`, `bell`, `fm`, `hollow`, `reed`.
- A **custom formula** is any periodic expression in `x`, up to 300 characters, e.g. `sin(2*pi*x) + 0.3*sin(6*pi*x)`. The formula is sampled once per cycle, so it must be defined everywhere in one period.

```bash
mathmusic instruments                      # list every waveform and instrument with its formulas
mathmusic "sin(x)" "x^2/8" --wave bell -o out/bells.mp3
mathmusic "sin(x)" --wave "sin(2*pi*x) + 0.5*sin(4*pi*x)" -o out/custom.mp3
```

In the UI, each expression has a sound menu. Choose **custom formula…** to type your own waveform.

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

## Licence

AGPL-3.0-or-later. See [LICENSE](LICENSE).
