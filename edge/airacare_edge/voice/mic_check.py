"""Manual live-mic smoke test — exercises the FULL voice path incl. the LLM.

    python -m airacare_edge.voice.mic_check

Warms up the models, records one utterance from the (Remote Audio) mic, transcribes it,
and interprets it via the keyword fast-path → Ollama (on ambiguous replies). Say
something clear ("I'm fine" / "help me") or deliberately ambiguous
("no need to fuss over me") to see the LLM engage. Requires the ``[audio]`` extra
(and Ollama running for the LLM step).
"""

from __future__ import annotations

from pathlib import Path

from airacare_edge.config import EdgeConfig
from airacare_edge.voice.service import LocalVoiceService


def main() -> None:
    from airacare_edge._console import ensure_utf8_stdout

    ensure_utf8_stdout()
    config_path = Path(__file__).resolve().parents[2] / "config.yaml"
    config = EdgeConfig.load(config_path)
    # Force live mic for this check regardless of config.
    config = config.model_copy(
        update={"voice": config.voice.model_copy(update={"input": "mic"})}
    )
    service = LocalVoiceService(config)

    print("⏳ warming up models (whisper + phi3.5)…")
    print(f"   warm-up: {service.warm_up()}")

    print("🎙️  Speak now (clear: 'I'm fine' / 'help me'; ambiguous: 'no need to fuss')… up to 8s.")
    transcript = service.listen(config.thresholds.no_response_seconds)
    if transcript is None:
        print("… no speech detected (→ NO RESPONSE → would escalate).")
        return

    intent = service.interpret(transcript)
    prov = service.last_interpretation or {}
    print(f'   transcript: "{transcript}"')
    print(f"   keyword fast-path said: {prov.get('keyword')}")
    if prov.get("llm_used"):
        llm_result = prov.get("llm_result")
        if llm_result in ("ok", "distress"):
            print(f"   → 'unclear' → 🧠 LLM re-interpreted it as: {llm_result}")
        else:
            print(f"   → 'unclear' → 🧠 LLM consulted (result={llm_result}); kept 'unclear'")
    else:
        print("   → resolved by keyword fast-path (LLM NOT called)")
    print(f"   FINAL intent: status={intent.status} urgency={intent.urgency:.2f}")


if __name__ == "__main__":
    main()
