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


Param = float | np.ndarray  # a constant, or one value per sample (automation)


def _per_sample(value: Param, x: np.ndarray) -> Param:
    """Shape a per-sample parameter so it broadcasts against x."""
    if isinstance(value, np.ndarray) and x.ndim == 2:
        return value[:, None]
    return value


def comb(x: np.ndarray, delay: int, gain: Param) -> np.ndarray:
    """Feedback comb y[n] = x[n] + gain*y[n-delay].

    Computed one delay-length block at a time: each block only depends on the
    block before it, so the work is vectorised instead of per sample. A
    per-sample gain is applied block by block.
    """
    y = np.array(x, dtype=np.float64, copy=True)
    n = len(y)
    delay = max(1, int(delay))
    varying = isinstance(gain, np.ndarray)
    for start in range(delay, n, delay):
        end = min(start + delay, n)
        g = gain[start:end] if varying else gain
        y[start:end] += g * y[start - delay : end - delay]
    return y


def allpass(x: np.ndarray, delay: int, gain: float) -> np.ndarray:
    """Schroeder allpass y[n] = -g*x[n] + x[n-D] + g*y[n-D]."""
    return comb(-gain * x + _shift(x, delay), delay, gain)


def shaper(x: np.ndarray, formula: str, mix: Param) -> np.ndarray:
    shaped = Expression(formula).evaluate(x)
    shaped = np.nan_to_num(shaped, nan=0.0, posinf=0.0, neginf=0.0)
    mix = _per_sample(mix, x)
    return (1 - mix) * x + mix * shaped


def _biquad_coefficients(kind: str, cutoff: float, q: float, sample_rate: int):
    w0 = 2 * pi * min(cutoff, sample_rate * 0.45) / sample_rate
    alpha = sin(w0) / (2 * q)
    c = cos(w0)
    if kind == "lowpass":
        b = [(1 - c) / 2, 1 - c, (1 - c) / 2]
    else:
        b = [(1 + c) / 2, -(1 + c), (1 + c) / 2]
    a = [1 + alpha, -2 * c, 1 - alpha]
    return np.array(b) / a[0], np.array(a) / a[0]


FILTER_BLOCK = 256  # samples per coefficient update when cutoff or q is automated


def biquad(x: np.ndarray, kind: str, cutoff: Param, q: Param, sample_rate: int) -> np.ndarray:
    if not isinstance(cutoff, np.ndarray) and not isinstance(q, np.ndarray):
        b, a = _biquad_coefficients(kind, float(cutoff), float(q), sample_rate)
        return lfilter(b, a, x, axis=0)
    # time-varying: recompute the coefficients every block and carry the filter state across
    out = np.empty_like(x, dtype=np.float64)
    state = np.zeros((2,) + x.shape[1:])
    for start in range(0, len(x), FILTER_BLOCK):
        end = min(start + FILTER_BLOCK, len(x))
        mid = (start + end) // 2
        fc = cutoff[mid] if isinstance(cutoff, np.ndarray) else cutoff
        qq = q[mid] if isinstance(q, np.ndarray) else q
        b, a = _biquad_coefficients(kind, float(fc), float(qq), sample_rate)
        out[start:end], state = lfilter(b, a, x[start:end], axis=0, zi=state)
    return out


def delay(x: np.ndarray, samples: int, feedback: Param, mix: Param) -> np.ndarray:
    samples = max(1, int(samples))
    wet = np.stack([comb(_shift(x[:, ch], samples), samples, feedback) for ch in range(x.shape[1])], axis=1)
    mix = _per_sample(mix, x)
    return (1 - mix) * x + mix * wet


_COMB_MS = (29.7, 37.1, 41.1, 43.7)
_ALLPASS = ((5.0, 0.7), (1.7, 0.7))
_STEREO_SPREAD = 23  # samples added to the right channel's delays


def reverb(x: np.ndarray, size: float, damping: float, mix: Param, sample_rate: int) -> np.ndarray:
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
    mix = _per_sample(mix, x)
    return (1 - mix) * x + mix * wet


def apply_effect(x: np.ndarray, kind: str, params: dict, sample_rate: int, seconds_per_beat: float) -> np.ndarray:
    """Apply one effect. Number params are floats, or per-sample arrays when automated."""
    if kind == "shaper":
        return shaper(x, str(params["formula"]), params["mix"])
    if kind in ("lowpass", "highpass"):
        return biquad(x, kind, params["cutoff"], params["q"], sample_rate)
    if kind == "delay":
        samples = int(float(params["time"]) * seconds_per_beat * sample_rate)
        return delay(x, samples, params["feedback"], params["mix"])
    if kind == "reverb":
        return reverb(x, float(params["size"]), float(params["damping"]), params["mix"], sample_rate)
    raise ValueError(f"unknown effect {kind!r}")
