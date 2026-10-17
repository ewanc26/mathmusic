"""Upload a rendered track to plyr.fm (music on AT Protocol).

Uses the plyrfm SDK. The token comes from PLYR_TOKEN, which is created at
plyr.fm/settings#developer. The account needs an artist profile on plyr.fm.
"""

from __future__ import annotations

import os
from pathlib import Path


def publish_to_plyr(
    audio_path: Path,
    title: str,
    *,
    album: str | None = None,
    tags: set[str] | None = None,
    description: str | None = None,
) -> int:
    """Upload the file and return the new plyr.fm track id."""
    try:
        from plyrfm import PlyrClient
    except ImportError as exc:
        raise RuntimeError("publishing needs the plyrfm package: uv pip install plyrfm==0.0.1a25") from exc

    token = os.environ.get("PLYR_TOKEN")
    if not token:
        raise RuntimeError(
            "PLYR_TOKEN is not set. Create a developer token at plyr.fm/settings#developer, "
            "then: export PLYR_TOKEN=..."
        )

    client = PlyrClient(token=token)
    try:
        result = client.tracks.upload(
            audio_path,
            title,
            album=album,
            tags=tags,
            description=description,
        )
    except Exception as exc:  # network, auth and API errors all reach the user the same way
        raise RuntimeError(f"the upload to plyr.fm failed: {exc}") from exc
    return result.track_id
