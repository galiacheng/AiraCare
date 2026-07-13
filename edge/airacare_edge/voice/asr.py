"""Speech-to-text via faster-whisper (the agent's *transcriber*).

CPU + int8 for the target hardware. The model is loaded lazily and cached; it
auto-downloads on first use. Accepts either a WAV path or a float32 mono numpy array.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid importing numpy at module import time
    import numpy as np


class WhisperTranscriber:
    def __init__(self, model_size: str = "base", compute_type: str = "int8") -> None:
        self._model_size = model_size
        self._compute_type = compute_type
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel  # lazy

            self._model = WhisperModel(
                self._model_size, device="cpu", compute_type=self._compute_type
            )
        return self._model

    def transcribe_file(self, wav_path: str | Path) -> str:
        model = self._ensure_model()
        segments, _ = model.transcribe(str(wav_path), language="en")
        return " ".join(segment.text for segment in segments).strip()

    def transcribe_array(self, samples: "np.ndarray", sample_rate: int = 16000) -> str:
        # faster-whisper expects 16 kHz float32 mono.
        model = self._ensure_model()
        segments, _ = model.transcribe(samples, language="en")
        return " ".join(segment.text for segment in segments).strip()
