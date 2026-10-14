"""mathmusic: turn mathematical curves into music."""

from mathmusic.composer import NoteEvent, Options, Voice, build_voices
from mathmusic.expr import Expression, ExpressionError

__all__ = ["Expression", "ExpressionError", "NoteEvent", "Options", "Voice", "build_voices"]
__version__ = "0.1.0"
