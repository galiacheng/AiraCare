"""Manual live-mic smoke test — speak after the prompt and see the transcription.

    python -m airacare_edge.voice.mic_check

Records one utterance from the (Remote Audio) mic, transcribes it, and prints the
keyword intent. Requires the ``[audio]`` extra.
"""

from __future__ import annotations

from airacare_edge.voice.asr import WhisperTranscriber
from airacare_edge.voice.nlu import keyword_intent
from airacare_edge.voice.vad import record_until_silence


def main() -> None:
    sample_rate = 16000
    print("🎙️  Speak now (say e.g. 'I'm fine' or 'help me')… waiting up to 8s.")
    samples = record_until_silence(sample_rate=sample_rate, start_timeout=8.0)
    if samples is None:
        print("… no speech detected (this would be treated as NO RESPONSE → escalate).")
        return

    print("📝 transcribing…")
    text = WhisperTranscriber(model_size="base").transcribe_array(samples, sample_rate)
    intent = keyword_intent(text)
    print(f'   transcript: "{text}"')
    print(f"   intent:     status={intent.status} urgency={intent.urgency:.2f}")


if __name__ == "__main__":
    main()
