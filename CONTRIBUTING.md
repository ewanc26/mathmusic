# Contributing to mathmusic

A DAW where every clip, sound, envelope, automation and effect is a formula, with optional publishing to plyr.fm.

## Project context

- Primary languages: Python (3.10+) for the engine; SvelteKit (Svelte 5, TypeScript, Tailwind v4) for the UI in `frontend/`
- Default branch: main

## Setup

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e ".[plot,publish,dev]"
cd frontend && pnpm install
```

## Before submitting changes

- Read the README, `pyproject.toml`, `frontend/package.json`, and nearby code before choosing commands.
- Run `.venv/bin/python -m pytest` and check the result before opening a pull request.
- For UI changes, run `pnpm check` and `pnpm build` in `frontend/`, commit the rebuilt `src/mathmusic/web/`, and check the affected view with `mathmusic serve --no-browser` (or `pnpm dev` against it).
- Format the frontend with `pnpm format`, or install the pre-commit hook: `pre-commit install`.
- Keep commits focused and explain compatibility or operational impact.
- Use conventional commit messages (`feat:`, `fix:`, `docs:`, `chore:`, `test:`).
- Open changes through a pull request with verification results.
