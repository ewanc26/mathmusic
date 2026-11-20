# Contributing to mathmusic

A DAW where everything is a graph. Each clip plays a curve `y = f(x)` read as time, sounds, envelopes, automation and effects are formulas too, and every one is drawn while you edit. `mathmusic serve` opens the DAW at http://127.0.0.1:8765. Thank you for wanting to help!

## Getting started

```bash
mathmusic serve          # open the DAW at http://127.0.0.1:8765
```

Audio import, microphone recording and MP3 export need **ffmpeg** on the system. Projects are JSON under `~/.ewanc26/mathmusic/projects` (or `$MATHMUSIC_HOME`), samples converted to 44.1 kHz stereo and stored by content in `assets/`.

## Notes for this project

- **The formula is the data.** Clips, sounds, envelopes, automation and effect parameters are all expressions in `x` (the beat); prefer extending the expression surface over adding special-case fields.
- The metronome click is a Web Audio sine burst and is **never part of the render or the exports** — keep it out of the signal path.
- Undo/redo must cover every editing change; a feature without undo is unfinished.
- Effect chains exist per track and on the master, with buses as effect-return tracks — keep parameter automation (press **ƒ**) working for every new effect parameter.
- Exports (WAV/MP3/MIDI) must match what the playhead plays; the MIDI export uses the same notes with program choices resembling each sound.

## Before opening a PR

- The documented build and tests pass, and you ran them yourself.
- Conventional commits; one focused PR per change.
- AI-assisted PRs are welcome; stand behind every line.

## Licence

AGPL-3.0 (see [LICENSE](LICENSE)). Contributions are accepted under the same terms. Contributions are accepted under the same terms.