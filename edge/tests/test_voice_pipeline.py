"""Voice pipeline tests.

- ``keyword_intent`` runs everywhere (pure logic).
- The TTS->ASR round-trip and energy-VAD tests are guarded with ``importorskip`` so the
  suite still passes without the ``[audio]`` extra installed.
"""

from __future__ import annotations

import pytest

from airacare_edge.voice.nlu import keyword_intent


@pytest.mark.parametrize(
    "text,expected",
    [
        ("I'm fine", "ok"),
        ("okay thanks", "ok"),
        ("yep yep yep", "ok"),            # affirmations: yep/yeah/yup
        ("yeah I'm good", "ok"),
        ("help me", "distress"),
        ("I fell and it hurts", "distress"),
        ("", "no_response"),
        ("   ", "no_response"),
        ("the garden over there", "unclear"),
        # regression: whole-word matching — "ok" must NOT match inside "looking"
        ("just looking for some garden", "unclear"),
        ("What do you mean? I don't understand.", "unclear"),
    ],
)
def test_keyword_intent(text, expected):
    assert keyword_intent(text).status == expected


def test_energy_vad_detects_speech_vs_silence():
    np = pytest.importorskip("numpy")
    from airacare_edge.voice.vad import has_speech

    sample_rate = 16000
    t = np.linspace(0, 1.0, sample_rate, dtype="float32")
    tone = (0.3 * np.sin(2 * np.pi * 220 * t)).astype("float32")  # loud-ish tone
    silence = np.zeros(sample_rate, dtype="float32")

    assert has_speech(tone, energy_threshold=0.02)
    assert not has_speech(silence, energy_threshold=0.02)


@pytest.mark.slow
def test_tts_to_asr_roundtrip(tmp_path):
    """Speak text with SAPI, transcribe it back with whisper — no human needed."""
    pytest.importorskip("pyttsx3")
    pytest.importorskip("faster_whisper")

    from airacare_edge.voice.asr import WhisperTranscriber
    from airacare_edge.voice.tts import SapiTTS

    wav = tmp_path / "prompt.wav"
    SapiTTS().synthesize("Grandpa, are you okay", wav)
    assert wav.exists() and wav.stat().st_size > 0

    text = WhisperTranscriber(model_size="tiny").transcribe_file(wav).lower()
    # SAPI is clear; whisper-tiny should recover a key word.
    assert "okay" in text or "grandpa" in text
