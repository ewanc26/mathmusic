"""Effects, each a small piece of signal-processing maths.

All functions take and return float arrays of shape (samples, 2).

- shaper: y = f(x), a transfer curve applied to every sample
- lowpass / highpass: RBJ biquad filters
- delay: a feedback delay line, w[n] = x[n-D] + g*w[n-D]
- reverb: Schroeder reverb, four parallel combs then two allpasses
"""

from __future__ import annotations

from math import cos, pi, sin

import numpy as np
from scipy.signal import lfilter

from mathmusic.expr import Expression


def _shift(x: np.ndarray, delay: int) -> np.ndarray:
    """x delayed by `delay` samples, zero-filled at the start."""
    out = np.zeros_like(x)
    if delay < len(x):
        out[delay:] = x[: len(x) - delay]
    return out


def comb(x: np.ndarray, delay: int, gain: float) -> np.ndarray:
    """Feedback comb y[n] = x[n] + gain*y[n-delay].

    Computed one delay-length block at a time: each block only depends on the
    block before it, so the work is vectorised instead of per sample.
    """
    y = np.array(x, dtype=np.float64, copy=True)
    n = len(y)
    delay = max(1, int(delay))
    for start in range(delay, n, delay):
        end = min(start + delay, n)
        y[start:end] += gain * y[start - delay : end - delay]
    return y


def allpass(x: np.ndarray, delay: int, gain: float) -> np.ndarray:
    """Schroeder allpass y[n] = -g*x[n] + x[n-D] + g*y[n-D]."""
    return comb(-gain * x + _shift(x, delay), delay, gain)


def shaper(x: np.ndarray, formula: str, mix: float) -> np.ndarray:
    shaped = Expression(formula).evaluate(x)
    shaped = np.nan_to_num(shaped, nan=0.0, posinf=0.0, neginf=0.0)
    return (1 - mix) * x + mix * shaped


def biquad(x: np.ndarray, kind: str, cutoff: float, q: float, sample_rate: int) -> np.ndarray:
    w0 = 2 * pi * min(cutoff, sample_rate * 0.45) / sample_rate
    alpha = sin(w0) / (2 * q)
    c = cos(w0)
    if kind == "lowpass":
        b = [(1 - c) / 2, 1 - c, (1 - c) / 2]
    else:
        b = [(1 + c) / 2, -(1 + c), (1 + c) / 2]
    a = [1 + alpha, -2 * c, 1 - alpha]
    return lfilter(np.array(b) / a[0], np.array(a) / a[0], x, axis=0)


def delay(x: np.ndarray, samples: int, feedback: float, mix: float) -> np.ndarray:
    samples = max(1, int(samples))
    wet = np.stack([comb(_shift(x[:, ch], samples), samples, feedback) for ch in range(x.shape[1])], axis=1)
    return (1 - mix) * x + mix * wet


_COMB_MS = (29.7, 37.1, 41.1, 43.7)
_ALLPASS = ((5.0, 0.7), (1.7, 0.7))
_STEREO_SPREAD = 23  # samples added to the right channel's delays


def reverb(x: np.ndarray, size: float, damping: float, mix: float, sample_rate: int) -> np.ndarray:
    scale = 0.6 + 0.8 * size  # bigger rooms, longer delays
    feedback = min(0.7 + 0.25 * size, 0.95)
    channels = []
    for ch in range(x.shape[1]):
        spread = _STEREO_SPREAD * ch
        dry = x[:, ch]
        wet = sum(comb(dry, int(ms * scale * sample_rate / 1000) + spread, feedback) for ms in _COMB_MS)
        wet = wet / len(_COMB_MS)
        wet = lfilter([1 - damping], [1, -damping], wet)  # one-pole lowpass darkens the tail
        for ms, gain in _ALLPASS:
            wet = allpass(wet, int(ms * sample_rate / 1000) + spread, gain)
        channels.append(wet)
    wet = np.stack(channels, axis=1)
    return (1 - mix) * x + mix * wet


def apply_effect(x: np.ndarray, kind: str, params: dict, sample_rate: int, seconds_per_beat: float) -> np.ndarray:
    if kind == "shaper":
        return shaper(x, str(params["formula"]), float(params["mix"]))
    if kind in ("lowpass", "highpass"):
        return biquad(x, kind, float(params["cutoff"]), float(params["q"]), sample_rate)
    if kind == "delay":
        samples = int(float(params["time"]) * seconds_per_beat * sample_rate)
        return delay(x, samples, float(params["feedback"]), float(params["mix"]))
    if kind == "reverb":
        return reverb(x, float(params["size"]), float(params["damping"]), float(params["mix"]), sample_rate)
    raise ValueError(f"unknown effect {kind!r}")
