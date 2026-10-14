"""Save and load projects as JSON files.

Projects live in $MATHMUSIC_HOME/projects (default ~/.ewanc26/mathmusic/projects).
Names are restricted to letters, digits, spaces, '-' and '_' so they map
directly to file names without any path tricks.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from mathmusic.project import parse_project, project_to_dict

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,63}")
SUFFIX = ".json"


def projects_dir() -> Path:
    home = Path(os.environ.get("MATHMUSIC_HOME") or Path.home() / ".ewanc26" / "mathmusic")
    return home / "projects"


def _path(name: str) -> Path:
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError("project names are 1-64 letters, digits, spaces, '-' or '_', starting with a letter or digit")
    return projects_dir() / f"{name}{SUFFIX}"


def list_projects() -> list[dict]:
    folder = projects_dir()
    if not folder.is_dir():
        return []
    items = []
    for path in folder.glob(f"*{SUFFIX}"):
        name = path.name[: -len(SUFFIX)]
        if not _NAME.fullmatch(name):
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
        items.append({"name": name, "modified": modified})
    return sorted(items, key=lambda item: item["modified"], reverse=True)


def load_project(name: str) -> dict:
    path = _path(name)
    if not path.is_file():
        raise LookupError(f"no project named {name!r}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return project_to_dict(parse_project(raw))  # validate and fill defaults


def save_project(name: str, raw: dict) -> dict:
    path = _path(name)
    project = parse_project(raw)
    project.name = name
    data = project_to_dict(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(path)  # atomic on the same filesystem
    return data
