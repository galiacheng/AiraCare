"""Privacy scrub — derive a small, non-reconstructable feature vector from raw audio.

This is the code embodiment of the privacy boundary: the raw waveform is reduced to a
handful of aggregate acoustic statistics (duration, loudness, activity), from which the
original speech cannot be reconstructed. The raw samples are never stored on or
referenced by the returned value, and never leave the device.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    import numpy as np


def scrub_audio_features(
    samples: "Sequence[float] | np.ndarray | None",
    sample_rate: int = 16000,
) -> list[float]:
    """Return privacy-scrubbed acoustic features: [duration_s, rms, zcr, peak].

    - duration_s : utterance length in seconds
    - rms        : root-mean-square energy (loudness proxy)
    - zcr        : zero-crossing rate (rough voicing/activity proxy)
    - peak       : peak absolute amplitude
    None of these can reconstruct the spoken words.
    """
    import numpy as np

    if samples is None:
        return []
    arr = np.asarray(samples, dtype="float64").ravel()
    if arr.size == 0:
        return []

    duration = arr.size / float(sample_rate)
    rms = float(np.sqrt(np.mean(np.square(arr))))
    zcr = float(np.mean((np.abs(np.diff(np.sign(arr))) > 0).astype("float64")))
    peak = float(np.max(np.abs(arr)))
    return [round(duration, 3), round(rms, 4), round(zcr, 4), round(peak, 4)]
