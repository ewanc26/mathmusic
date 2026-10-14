# Contributing to mathmusic

Turns mathematical curves into music, with a local graphing UI and optional publishing to plyr.fm.

## Project context

- Primary language: Python (3.10+); the UI is plain HTML, CSS and JavaScript
- Default branch: main

## Setup

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e ".[plot,publish,dev]"
```

## Before submitting changes

- Read the README, `pyproject.toml`, and nearby code before choosing commands.
- Run `.venv/bin/python -m pytest` and check the result before opening a pull request.
- For UI changes, run `mathmusic serve --no-browser` and check the affected view in a browser.
- Keep commits focused and explain compatibility or operational impact.
- Use conventional commit messages (`feat:`, `fix:`, `docs:`, `chore:`, `test:`).
- Open changes through a pull request with verification results.
