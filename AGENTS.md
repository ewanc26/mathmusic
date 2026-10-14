# AGENTS.md

Guidance for AI coding agents working in **mathmusic**.

## Project overview

Turns mathematical curves into music, with a local graphing UI and optional publishing to plyr.fm.

- Language: Python (3.10+), with plain JavaScript and CSS for the UI in `src/mathmusic/web/`
- Default branch: main
- Validation: `.venv/bin/python -m pytest` (the test suite is in `tests/`)

## Working rules

- Inspect the README, manifests, CI workflows, and nearby code before editing.
- Preserve existing architecture, naming, formatting, and error-handling conventions.
- Use project scripts for validation; never claim checks you did not run.
- Keep changes scoped and update tests or documentation when behavior changes.
- Use feature branches and pull requests.
- Treat generated files, credentials, deployment configuration, and release metadata as sensitive.
- Expressions are user input. Keep the parser in `expr.py` whitelist-based; never evaluate raw strings with `eval` outside it.
- Never commit `PLYR_TOKEN` values or `.env` files. Publishing reads the token from the environment only.
