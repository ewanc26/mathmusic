# mathmusic

A DAW where everything is a graph. Music is arranged from mathematical curves: each clip plays a curve `y = f(x)`, read left to right as time, with its height mapped to pitch. Sounds, envelopes, automation and effects are formulas too, and every one of them is drawn as a graph while you edit it.

```bash
mathmusic serve            # opens the DAW at http://127.0.0.1:8765
```

## The DAW

- **Arrangement:** tracks of clips on a beat timeline. Drag clips to move them, including onto another track. Drag a clip's right edge to resize it, and double-click a lane to add one. Each lane shows its clips' curves, the track's rendered waveform, and its automation.
- **Clip editor:** the curve plotted against the scale's pitch lattice. Each horizontal line is a note, and each sample snaps to the nearest one. You set the expression, the x range, the number of notes, the start and length in beats, the rhythm, octave, range, gate and gain, invert, and an optional fixed y range.
- **Tracks:** a sound (waveform, instrument or your own formula), an envelope over each note, volume, pan, mute and solo. The waveform's single cycle and the envelope are both plotted.
- **Effects:** chains on every track and on the master: a waveshaper with a formula transfer curve, lowpass and highpass biquads, a feedback delay in beats, and a Schroeder reverb. You can bypass and reorder them.
- **Automation:** gain and pan as formulas of the beat, plotted over the song, with presets for fades, tremolo, swells and auto-pan.
- **Mixer:** channel strips with faders, pan, mute and solo, and level meters that follow the playhead.
- **Transport:** play and pause, loop (drag on the ruler), a bar.beat position, follow-playhead, and zoom.
- **Editing:** undo and redo for every change, copy, paste, duplicate, split at the playhead, and delete. Keyboard shortcuts are listed under `?`.
- **Projects:** save and open by name, plus an automatic draft in the browser. Projects are stored as JSON in `~/.mathmusic/projects`, or in `$MATHMUSIC_HOME/projects` if that's set.
- **Export:** WAV, MP3 and MIDI. The MIDI file uses the same notes you hear, with General MIDI programs chosen to resemble each sound.
- **Publish:** upload the mix to plyr.fm. See below.

### Everything is a formula in x

| Where | What x means | Example |
| --- | --- | --- |
| Clip | runs across the clip from "x from" to "x to" | `sin(x)*exp(-x/8)` |
| Waveform | phase, one cycle from 0 to 1 | `sin(2*pi*x) + 0.3*sin(6*pi*x)` |
| Envelope | position in the note, 0 to 1 | `exp(-4*x)` |
| Gain automation | song position in beats; multiplies the volume | `min(1, x/8)` |
| Pan automation | song position in beats; added to the pan | `sin(2*pi*x/8)` |
| Shaper effect | the audio sample value | `tanh(3*x)` |

Formulas accept `+ - * / ^ %`, `x`, `pi`, `tau`, `e`, and functions such as `sin cos tan exp log sqrt abs floor sign sinc tanh mod min max clip`. Anything else is rejected before evaluation. A formula that fails is reported on the clip, sound or effect that uses it, and the rest of the project still plays.

### How a clip becomes notes

- The curve is sampled at **notes** points across its x range. Each sample is one note, and together they fill the clip's length.
- The y value maps onto the project's **scale** across **range** octaves, starting from the root plus the clip's **octave**. By default the curve's own min and max span the range. A **fixed y range** gives the same y the same pitch in every clip.
- **Rhythm** `slope` gives steep parts of the curve shorter notes. **Gate** sets how much of each step sounds.
- Undefined points (`log(-1)`, division by zero) become rests.

### Sounds

- **Waveforms:** `sine`, `triangle`, `saw`, `square`, `pulse`.
- **Instruments:** each pairs a waveform with an envelope. `organ`, `clarinet` (odd harmonics), `brass`, `pluck`, `bell` (inharmonic partials), `fm`, `hollow`, `reed`.
- **Custom formula:** any periodic expression in `x`, up to 300 characters. It must be defined over the whole cycle.

`mathmusic instruments` prints every waveform and instrument with its formulas.

## Command line

```bash
mathmusic render ~/.mathmusic/projects/"My Song".json -o song.mp3   # render a saved project (.mp3, .wav or .mid)
mathmusic "sin(x)" "x^2/8" --wave bell -o sketch.mp3                # quick sketch from expressions, no project
mathmusic instruments
```

The sketch mode keeps its original options: `--start`, `--end`, `--samples`, `--scale`, `--octaves`, `--pitch-range shared|per-voice`, `--rhythm`, `--wave`, `--plot` and `--publish`. Run `mathmusic --help` for the full list.

## Setup

Needs Python 3.10+, and ffmpeg for MP3 (`brew install ffmpeg`).

```bash
uv venv .venv && uv pip install --python .venv/bin/python -e ".[plot,publish,dev]"
.venv/bin/mathmusic serve
```

The server listens only on 127.0.0.1. It refuses requests whose Host or Origin isn't the local address, so other websites can't use it to render, save or publish.

## Publishing to plyr.fm

The Publish tab, or `--publish` in sketch mode, uploads the mix as an MP3 to [plyr.fm](https://plyr.fm), which is music on AT Protocol. Create a developer token at plyr.fm/settings#developer, then `export PLYR_TOKEN=…` before starting mathmusic. Your account needs an artist profile. Uploads go through the [`plyrfm`](https://pypi.org/project/plyrfm/) SDK.

## Tests

```bash
.venv/bin/python -m pytest
```

## Licence

AGPL-3.0-or-later. See [LICENSE](LICENSE).
