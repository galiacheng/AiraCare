"""LocalVoiceService — the real voice pipeline behind the VoiceService protocol.

    say(text)          -> TTS (Piper/SAPI)                         [agent speaks]
    listen(timeout)    -> mic -> VAD (no-response timeout) -> ASR  [agent hears]
    interpret(text)    -> keyword fast-path (step 4 rule path)     [agent understands]

Everything heavy is created lazily, so importing this module needs no audio deps. The
Edge Core FSM is unchanged — it only sees the VoiceService protocol.
"""

from __future__ import annotations

from pathlib import Path

from airacare_edge.cloud.contracts import ReplyIntent
from airacare_edge.config import EdgeConfig
from airacare_edge.voice.nlu import keyword_intent


class LocalVoiceService:
    def __init__(self, config: EdgeConfig, reply_wav: str | Path | None = None) -> None:
        self._config = config
        self._reply_wav = reply_wav  # used only in voice.input == "file" mode
        self._tts = None
        self._asr = None

    # --- lazy backends -------------------------------------------------------
    def _get_tts(self):
        if self._tts is None:
            from airacare_edge.voice.tts import make_tts

            self._tts = make_tts(self._config.voice.tts_engine, self._config.voice.tts_voice)
        return self._tts

    def _get_asr(self):
        if self._asr is None:
            from airacare_edge.voice.asr import WhisperTranscriber

            self._asr = WhisperTranscriber(model_size=self._config.voice.asr_model)
        return self._asr

    # --- VoiceService protocol ----------------------------------------------
    def say(self, text: str) -> None:
        self._get_tts().speak(text)

    def listen(self, timeout: float) -> str | None:
        voice = self._config.voice
        if voice.input == "file":
            if not self._reply_wav:
                return None  # no scripted reply -> treated as no response
            text = self._get_asr().transcribe_file(self._reply_wav)
            return text or None

        from airacare_edge.voice.vad import record_until_silence

        samples = record_until_silence(
            sample_rate=voice.sample_rate,
            start_timeout=timeout,
            silence_seconds=voice.silence_seconds,
            energy_threshold=voice.energy_threshold,
        )
        if samples is None:
            return None
        text = self._get_asr().transcribe_array(samples, voice.sample_rate)
        return text or None

    def interpret(self, transcript: str) -> ReplyIntent:
        # Step 4: keyword fast-path only. Step 5 adds Ollama for 'unclear' replies.
        return keyword_intent(transcript)
