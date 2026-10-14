# AGENTS.md

Guidance for AI coding agents working in **mathmusic**.

## Project overview

A DAW where every clip, sound, envelope, automation and effect is a formula, with a local browser UI and optional publishing to plyr.fm.

- Languages: Python (3.10+) for the engine and server; SvelteKit (Svelte 5 runes, TypeScript, Tailwind v4, pnpm) for the UI in `frontend/`
- Default branch: main
- Validation: `.venv/bin/python -m pytest`; for UI changes `pnpm check` and `pnpm build` in `frontend/`, then `mathmusic serve` and check in a browser

## Layout

- `src/mathmusic/`: `project.py` (model, validation, limits), `engine.py` (renders clips, samples, tracks, effects, master), `dsp.py` (effects, including automated parameters), `waves.py` (waveforms, instruments), `assets.py` (imported samples), `midi.py` (MIDI export), `storage.py` (project files), `server.py` (local HTTP API, serves the built UI), `cli.py`.
- `frontend/src/lib/`: `daw.svelte.ts` (state, undo/redo, rendering, autosave), `transport.svelte.ts` (playback, metronome), `view.svelte.ts` (zoom/scroll/snap), `actions.svelte.ts` (commands), `draw.ts` (canvas graphs), `components/` (TopBar, Arrangement, TrackHeader, Panel and its editors).
- `src/mathmusic/web/` is build output from `frontend/` (`pnpm build`). Do not edit it by hand; rebuild and commit it with the source change.
- All project edits in the UI go through `daw.edit()` or `daw.live()` + `daw.settle()` so they can be undone.

## Working rules

- Inspect the README, manifests, CI workflows, and nearby code before editing.
- Preserve existing architecture, naming, formatting, and error-handling conventions.
- Use project scripts for validation; never claim checks you did not run.
- Keep changes scoped and update tests or documentation when behavior changes.
- Use feature branches and pull requests.
- Treat generated files, credentials, deployment configuration, and release metadata as sensitive.
- Expressions are user input. Keep the parser in `expr.py` whitelist-based; never evaluate raw strings with `eval` outside it.
- Never commit `PLYR_TOKEN` values or `.env` files. Publishing reads the token from the environment only.
