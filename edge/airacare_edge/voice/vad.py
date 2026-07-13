"""Voice-activity detection + mic capture (the agent's *attention* and *ear*).

Uses a simple, dependency-light **energy VAD** (numpy) to decide when the patient is
speaking and to implement the safety-critical **no-response timeout**: if no speech
starts within ``start_timeout`` seconds we return None (treated as ``no_response``).

silero-VAD can replace the energy detector later via the ``[audio-neural]`` extra.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

_FRAME_SECONDS = 0.03  # 30 ms analysis frames


def rms_energy(samples: "np.ndarray") -> float:
    import numpy as np

    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples, dtype="float64"))))


def has_speech(samples: "np.ndarray", energy_threshold: float = 0.02) -> bool:
    return rms_energy(samples) > energy_threshold


def record_until_silence(
    sample_rate: int = 16000,
    start_timeout: float = 8.0,
    silence_seconds: float = 1.2,
    energy_threshold: float = 0.02,
    max_utterance_seconds: float = 15.0,
) -> "np.ndarray | None":
    """Capture one utterance from the mic.

    Returns the captured float32 mono audio, or ``None`` if no speech began within
    ``start_timeout`` (the no-response case that drives escalation).
    """
    import numpy as np
    import sounddevice as sd  # lazy; requires PortAudio

    frame_len = max(1, int(_FRAME_SECONDS * sample_rate))
    frame_dur = frame_len / sample_rate

    collected: list[np.ndarray] = []
    started = False
    silence_run = 0.0
    waited = 0.0

    with sd.InputStream(samplerate=sample_rate, channels=1, dtype="float32") as stream:
        while True:
            data, _ = stream.read(frame_len)
            samples = data[:, 0]
            speaking = has_speech(samples, energy_threshold)

            if not started:
                if speaking:
                    started = True
                    collected.append(samples)
                    silence_run = 0.0
                else:
                    waited += frame_dur
                    if waited >= start_timeout:
                        return None  # no response
            else:
                collected.append(samples)
                if speaking:
                    silence_run = 0.0
                else:
                    silence_run += frame_dur
                    if silence_run >= silence_seconds:
                        break
                captured = sum(chunk.shape[0] for chunk in collected) / sample_rate
                if captured >= max_utterance_seconds:
                    break

    if not collected:
        return None
    return np.concatenate(collected)
