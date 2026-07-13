"""Privacy scrub tests — features are aggregate and non-reconstructable."""

from __future__ import annotations

import pytest


def test_scrub_empty_returns_empty():
    from airacare_edge.privacy.scrub import scrub_audio_features

    assert scrub_audio_features(None) == []
    assert scrub_audio_features([]) == []


def test_scrub_silence_vs_tone():
    pytest.importorskip("numpy")
    import numpy as np

    from airacare_edge.privacy.scrub import scrub_audio_features

    sr = 16000
    silence = np.zeros(sr, dtype="float32")  # 1 second
    t = np.linspace(0, 1.0, sr, dtype="float32")
    tone = (0.3 * np.sin(2 * np.pi * 220 * t)).astype("float32")

    sil = scrub_audio_features(silence, sr)
    ton = scrub_audio_features(tone, sr)

    # 4 aggregate features, ~1.0s duration
    assert len(sil) == 4 and len(ton) == 4
    assert abs(sil[0] - 1.0) < 0.01 and abs(ton[0] - 1.0) < 0.01
    # tone has energy; silence does not
    assert ton[1] > sil[1]
    assert ton[3] > sil[3]
