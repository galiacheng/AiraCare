"""Text-to-speech backends (the agent's *mouth*).

Default backend is SAPI via ``pyttsx3`` — fully offline, no model download on Windows.
An optional Piper (neural) backend can be added later. All imports are lazy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class TextToSpeech(Protocol):
    def speak(self, text: str) -> None: ...

    def synthesize(self, text: str, wav_path: str | Path) -> None:
        """Write spoken audio to a WAV file (used for tests / offline playback)."""


class SapiTTS:
    """Windows SAPI5 TTS via pyttsx3 (offline, no model download)."""

    def __init__(self, voice: str | None = None, rate: int | None = None) -> None:
        self._voice = voice
        self._rate = rate

    def _new_engine(self):
        import pyttsx3  # lazy

        engine = pyttsx3.init()
        if self._rate is not None:
            engine.setProperty("rate", self._rate)
        if self._voice:
            for candidate in engine.getProperty("voices"):
                if self._voice.lower() in candidate.name.lower():
                    engine.setProperty("voice", candidate.id)
                    break
        return engine

    def speak(self, text: str) -> None:
        engine = self._new_engine()
        engine.say(text)
        engine.runAndWait()
        engine.stop()

    def synthesize(self, text: str, wav_path: str | Path) -> None:
        engine = self._new_engine()
        engine.save_to_file(text, str(wav_path))
        engine.runAndWait()
        engine.stop()


def make_tts(engine: str, voice: str | None = None) -> TextToSpeech:
    if engine == "sapi":
        return SapiTTS(voice=voice)
    if engine == "piper":
        raise NotImplementedError(
            "Piper backend not wired yet; install '.[audio-neural]' and implement PiperTTS."
        )
    raise ValueError(f"unknown tts engine: {engine}")
