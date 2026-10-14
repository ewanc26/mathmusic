"""Plot the curves being sonified, so the picture and the sound can be compared."""

from __future__ import annotations

from pathlib import Path

from mathmusic.composer import Voice


def plot_voices(voices: list[Voice], path: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=150)
    for voice in voices:
        ax.plot(voice.x, voice.y, marker="o", markersize=2.5, linewidth=1.2, label=f"y = {voice.expression.source}")
    ax.set_xlabel("x (time in the piece, left to right)")
    ax.set_ylabel("y (pitch)")
    ax.grid(alpha=0.3)
    ax.legend(loc="best", fontsize=8)
    ax.set_title("Curves sonified by mathmusic")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path
