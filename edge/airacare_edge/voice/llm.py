"""Ollama-backed reply understanding for *ambiguous* replies (step 5).

Only invoked when the keyword fast-path returns ``unclear`` and
``voice.use_llm_for_ambiguous`` is set. Output is constrained to a tiny JSON object to
keep latency low. Any failure (Ollama not running, bad JSON, timeout) returns ``None``
so the caller safely keeps the keyword result — the LLM is an enhancement, never a
dependency on the safety path.
"""

from __future__ import annotations

import json

from airacare_edge.cloud.contracts import ReplyIntent

_SYSTEM = (
    "You classify an elderly patient's spoken reply to the question 'Are you okay?'. "
    'Respond with ONLY compact JSON: {"status":"ok|distress|unclear"}. '
    "ok = they are fine or reassuring. "
    "distress = they need help, are hurt, fell, or are frightened/confused. "
    "unclear = you genuinely cannot tell. Output no other text."
)

# Canonical urgency per status (keeps output consistent with the keyword path; the
# LLM only decides the status, not the urgency number).
_URGENCY = {"ok": 0.1, "distress": 0.9, "unclear": 0.5}


class OllamaInterpreter:
    def __init__(self, model: str = "phi3.5") -> None:
        self._model = model

    def warm_up(self) -> bool:
        """Load the model into memory so the first real call isn't a cold start."""
        try:
            import ollama  # lazy

            ollama.chat(
                model=self._model,
                messages=[{"role": "user", "content": "ready"}],
                options={"num_predict": 1},
            )
            return True
        except Exception:  # noqa: BLE001
            return False

    def interpret(self, transcript: str) -> ReplyIntent | None:
        try:
            import ollama  # lazy

            response = ollama.chat(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": transcript},
                ],
                format="json",
                options={"temperature": 0},
            )
            data = json.loads(response["message"]["content"])
        except Exception:  # noqa: BLE001 — any failure falls back to keyword result
            return None

        status = data.get("status")
        if status not in _URGENCY:
            return None
        return ReplyIntent(status=status, urgency=_URGENCY[status], transcript=transcript)
