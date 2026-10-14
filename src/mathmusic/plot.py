"""Plot the curves being sonified, so the picture and the sound can be compared."""

from __future__ import annotations

from pathlib import Path

from mathmusic.composer import Voice


def plot_voices(voices: list[Voice], path: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # One panel per voice with its own y-axis: voices can differ by orders of magnitude,
    # and on a shared axis the small curves flatten into the zero line.
    count = max(1, len(voices))
    fig, axes = plt.subplots(count, 1, figsize=(10, 2.2 * count + 0.8), dpi=150, sharex=True, squeeze=False)
    for ax, voice in zip(axes[:, 0], voices or [None]):
        if voice is None:
            ax.set_axis_off()
            continue
        ax.plot(voice.x, voice.y, marker="o", markersize=2.5, linewidth=1.2)
        ax.set_title(f"y = {voice.expression.source}", fontsize=9, loc="left")
        ax.set_ylabel("pitch", fontsize=8)
        ax.grid(alpha=0.3)
    axes[-1, 0].set_xlabel("x (time in the piece, left to right)")
    fig.suptitle("Curves sonified by mathmusic")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path
