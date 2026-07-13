"""Rule-based reply understanding (keyword fast-path).

This is the deterministic "interpret" used in step 4. Step 5 layers Ollama on top for
ambiguous replies; the keyword path here always runs first and resolves obvious cases
instantly (and is the safe fallback if the LLM is slow or unavailable).
"""

from __future__ import annotations

from airacare_edge.cloud.contracts import ReplyIntent

_DISTRESS = ("help", "fell", "fall", "can't", "cannot", "hurt", "pain", "emergency")
_OK = ("fine", "okay", "ok", "good", "yes", "alright", "all right", "fine thanks")


def keyword_intent(transcript: str | None) -> ReplyIntent:
    text = (transcript or "").strip().lower()
    if not text:
        return ReplyIntent(status="no_response", urgency=0.9, transcript=transcript)
    if any(word in text for word in _DISTRESS):
        return ReplyIntent(status="distress", urgency=0.95, transcript=transcript)
    if any(word in text for word in _OK):
        return ReplyIntent(status="ok", urgency=0.1, transcript=transcript)
    return ReplyIntent(status="unclear", urgency=0.5, transcript=transcript)
