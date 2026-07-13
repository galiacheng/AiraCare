"""Rule-based reply understanding (keyword fast-path).

This is the deterministic "interpret" used in step 4. Step 5 layers Ollama on top for
ambiguous replies; the keyword path here always runs first and resolves obvious cases
instantly (and is the safe fallback if the LLM is slow or unavailable).
"""

from __future__ import annotations

import re

from airacare_edge.cloud.contracts import ReplyIntent

# Whole-word matching (avoids substring false positives like "ok" inside "looking").
_DISTRESS_WORDS = {
    "help", "fell", "fall", "fallen", "falling",
    "hurt", "hurts", "pain", "emergency", "cannot", "can't", "stuck",
}
_DISTRESS_PHRASES = ("help me", "i fell", "i've fallen", "can't get up", "cannot get up")

_OK_WORDS = {"fine", "okay", "ok", "good", "great", "yes", "yeah", "yep", "yup", "sure", "alright"}
_OK_PHRASES = ("all right", "i'm fine", "im fine", "no worry", "no worries", "all good")

_NON_WORD = re.compile(r"[^a-z0-9']+")


def _normalize(text: str) -> str:
    return _NON_WORD.sub(" ", text.lower()).strip()


def keyword_intent(transcript: str | None) -> ReplyIntent:
    normalized = _normalize(transcript or "")
    if not normalized:
        return ReplyIntent(status="no_response", urgency=0.9, transcript=transcript)

    tokens = set(normalized.split())
    if tokens & _DISTRESS_WORDS or any(phrase in normalized for phrase in _DISTRESS_PHRASES):
        return ReplyIntent(status="distress", urgency=0.95, transcript=transcript)
    if tokens & _OK_WORDS or any(phrase in normalized for phrase in _OK_PHRASES):
        return ReplyIntent(status="ok", urgency=0.1, transcript=transcript)
    return ReplyIntent(status="unclear", urgency=0.5, transcript=transcript)
