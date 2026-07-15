"""Knowledge agent — RAG over care guidelines that grounds the cloud's advice (T2).

Because raw modality data never leaves the edge, the cloud's "knowledge access" is over
**care-guideline / clinical-protocol text**, not patient media. The Knowledge agent retrieves
the guideline snippets relevant to a reported event and distills a short, *grounded* advice
string with citations. It runs in the async deliberate tier — its output enriches records,
caregiver briefings, and the escalation narrative; it is **not** on the synchronous T1 path.

The retrieval backend is abstracted behind :class:`KnowledgeBase`:

- :class:`LocalKnowledgeBase` — a dependency-free in-memory index over a small seeded guideline
  set, scored by token overlap. Used for tests + the offline demo (no Azure needed).
- :class:`AzureSearchKnowledgeBase` — placeholder for real **Azure AI Search** vector RAG
  (install the ``[search]`` extra and implement); same protocol, drop-in.
"""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from airacare_foundry.contracts import CloudAssessment, DailyLivingEvent

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text.lower()))


class KnowledgeSnippet(BaseModel):
    """A single care-guideline passage retrieved from the knowledge base."""

    id: str
    title: str
    text: str
    tags: list[str] = Field(default_factory=list)

    def _haystack(self) -> set[str]:
        return _tokens(self.title) | _tokens(self.text) | {t.lower() for t in self.tags}


class GroundedAdvice(BaseModel):
    """Advice distilled from retrieved guidelines, with citations for explainability."""

    advice: str
    citations: list[str] = Field(default_factory=list)
    snippets: list[KnowledgeSnippet] = Field(default_factory=list)


# Small seeded care-guideline set for the flagship + adjacent scenarios (offline demo/tests).
DEFAULT_GUIDELINES: tuple[KnowledgeSnippet, ...] = (
    KnowledgeSnippet(
        id="kb-wander-night",
        title="Nighttime wandering response",
        text=(
            "Approach calmly from the front and speak softly; avoid startling the person. "
            "Gently reassure and guide them back to bed. Check for unmet needs such as "
            "toileting, thirst, or pain that may be driving the wandering."
        ),
        tags=["wander", "night", "dementia", "reassure"],
    ),
    KnowledgeSnippet(
        id="kb-wander-exit",
        title="Exit-seeking and elopement risk",
        text=(
            "If a door was opened, check the person's location and secure exits. Repeated "
            "nighttime exit-seeking is an elopement risk and warrants caregiver escalation."
        ),
        tags=["wander", "door", "elopement", "escalation"],
    ),
    KnowledgeSnippet(
        id="kb-fall",
        title="Suspected fall",
        text=(
            "Do not move the person if injury is suspected. Assess responsiveness and pain, "
            "keep them warm, and summon help. Falls with confusion warrant urgent review."
        ),
        tags=["fall", "injury", "emergency"],
    ),
    KnowledgeSnippet(
        id="kb-med",
        title="Missed medication",
        text=(
            "For a missed dose, follow the prescriber's guidance; do not double up. Log the "
            "miss and watch for symptom changes."
        ),
        tags=["med", "medication", "adherence"],
    ),
)


@runtime_checkable
class KnowledgeBase(Protocol):
    """Retrieve the guideline snippets most relevant to a free-text query."""

    def search(self, query: str, top_k: int = 2) -> list[KnowledgeSnippet]:
        ...


class LocalKnowledgeBase:
    """In-memory guideline index scored by token overlap — no external dependencies."""

    def __init__(self, snippets: tuple[KnowledgeSnippet, ...] | None = None) -> None:
        self._snippets = snippets if snippets is not None else DEFAULT_GUIDELINES

    def search(self, query: str, top_k: int = 2) -> list[KnowledgeSnippet]:
        q = _tokens(query)
        if not q:
            return []
        scored = [
            (len(q & snippet._haystack()), snippet)
            for snippet in self._snippets
        ]
        hits = [(score, s) for score, s in scored if score > 0]
        hits.sort(key=lambda pair: (-pair[0], pair[1].id))  # score desc, stable by id
        return [s for _, s in hits[:top_k]]


class AzureSearchKnowledgeBase:
    """Placeholder for real Azure AI Search vector RAG (install ``[search]`` and implement)."""

    _NOT_WIRED = (
        "AzureSearchKnowledgeBase is a placeholder in this scaffold. Use LocalKnowledgeBase; "
        "install the [search] extra and implement Azure AI Search vector RAG when ready."
    )

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError(self._NOT_WIRED)

    def search(self, query: str, top_k: int = 2) -> list[KnowledgeSnippet]:
        raise NotImplementedError(self._NOT_WIRED)


class KnowledgeAgent:
    """Grounds cloud advice in retrieved care guidelines (async T2 enrichment)."""

    def __init__(self, kb: KnowledgeBase | None = None, *, enabled: bool = True, top_k: int = 2) -> None:
        self.enabled = enabled
        self._kb = kb or LocalKnowledgeBase()
        self._top_k = top_k

    def advise(
        self, event: DailyLivingEvent, assessment: CloudAssessment | None = None
    ) -> GroundedAdvice | None:
        """Retrieve relevant guidelines and compose grounded advice, or None if nothing fits."""
        if not self.enabled:
            return None
        hits = self._kb.search(self._build_query(event, assessment), top_k=self._top_k)
        if not hits:
            return None
        level = assessment.considered_level if assessment is not None else event.edge_assessed_level
        lead = f"Guideline for {event.type} (considered {level})"
        advice = f"{lead}: {hits[0].text}"
        return GroundedAdvice(
            advice=advice,
            citations=[h.title for h in hits],
            snippets=list(hits),
        )

    @staticmethod
    def _build_query(event: DailyLivingEvent, assessment: CloudAssessment | None) -> str:
        parts = [event.type]
        ctx = event.context
        for key in ("time_of_day", "response"):
            value = ctx.get(key)
            if value:
                parts.append(str(value))
        if ctx.get("door_open"):
            parts.append("door")
        return " ".join(parts)
