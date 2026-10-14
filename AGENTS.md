# AGENTS.md

Guidance for AI coding agents working in **mathmusic**.

## Project overview

A DAW where every clip, sound, envelope, automation and effect is a formula, with a local browser UI and optional publishing to plyr.fm.

- Language: Python (3.10+), with plain ES-module JavaScript and CSS for the UI in `src/mathmusic/web/` (no build step)
- Default branch: main
- Validation: `.venv/bin/python -m pytest` (the test suite is in `tests/`); for UI changes, run `mathmusic serve` and check in a browser

## Layout

- `project.py`: the project model, validation and limits. `engine.py`: renders a project (clips, notes, tracks, effects, master). `dsp.py`: effects. `waves.py`: waveforms and instruments. `midi.py`: MIDI export. `storage.py`: project files.
- `server.py`: local HTTP API and static files. `cli.py`: `serve`, `render`, `instruments`, and the expression sketch mode.
- `web/js/`: `store.js` (state, undo, rendering), `arrange.js` (timeline), `tracks.js` (headers), `panels.js` (editor tabs), `graphs.js` (formula plots), `transport.js`, `main.js` (wiring).

## Working rules

- Inspect the README, manifests, CI workflows, and nearby code before editing.
- Preserve existing architecture, naming, formatting, and error-handling conventions.
- Use project scripts for validation; never claim checks you did not run.
- Keep changes scoped and update tests or documentation when behavior changes.
- Use feature branches and pull requests.
- Treat generated files, credentials, deployment configuration, and release metadata as sensitive.
- Expressions are user input. Keep the parser in `expr.py` whitelist-based; never evaluate raw strings with `eval` outside it.
- Never commit `PLYR_TOKEN` values or `.env` files. Publishing reads the token from the environment only.
