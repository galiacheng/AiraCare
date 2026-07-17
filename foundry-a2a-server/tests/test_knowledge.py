"""Knowledge agent tests: care-guideline retrieval grounds cloud advice (offline local KB)."""

from __future__ import annotations

import pytest

from airacare_foundry.agents.knowledge import (
    AzureSearchKnowledgeBase,
    KnowledgeAgent,
    KnowledgeBase,
    KnowledgeSnippet,
    LocalKnowledgeBase,
)
from airacare_foundry.contracts import CloudAssessment, DailyLivingEvent, utcnow


def _event(event_type: str = "wander", response: str = "no_response", **ctx) -> DailyLivingEvent:
    context = {"time_of_day": "night", "door_open": True, "response": response}
    context.update(ctx)
    return DailyLivingEvent(
        type=event_type,  # type: ignore[arg-type]
        confidence=0.9,
        timestamp=utcnow(),
        patient_id="p-001",
        baseline_deviation=0.95,
        edge_assessed_level="L3",
        edge_action_taken="escalated",
        context=context,
    )


def test_local_kb_satisfies_protocol() -> None:
    assert isinstance(LocalKnowledgeBase(), KnowledgeBase)


def test_local_kb_ranks_nighttime_wander_first() -> None:
    hits = LocalKnowledgeBase().search("wander night door", top_k=2)
    assert hits
    assert hits[0].id in {"kb-wander-night", "kb-wander-exit"}
    assert all(isinstance(h, KnowledgeSnippet) for h in hits)


def test_local_kb_empty_query_returns_nothing() -> None:
    assert LocalKnowledgeBase().search("   ") == []


def test_local_kb_no_match_returns_nothing() -> None:
    kb = LocalKnowledgeBase(
        (KnowledgeSnippet(id="only-fall", title="Fall", text="fall injury", tags=["fall"]),)
    )
    assert kb.search("medication adherence dose") == []


def test_agent_grounds_advice_with_citations() -> None:
    advice = KnowledgeAgent().advise(_event(), CloudAssessment(considered_level="L3", reason="x"))
    assert advice is not None
    assert "considered L3" in advice.advice
    assert advice.citations  # cited guideline titles
    assert advice.snippets
    # The advice text is grounded in the top retrieved snippet.
    assert advice.snippets[0].text in advice.advice


def test_agent_uses_edge_level_when_no_assessment() -> None:
    advice = KnowledgeAgent().advise(_event())
    assert advice is not None
    assert "considered L3" in advice.advice


def test_agent_disabled_returns_none() -> None:
    assert KnowledgeAgent(enabled=False).advise(_event()) is None


def test_agent_returns_none_when_no_relevant_guideline() -> None:
    kb = LocalKnowledgeBase(
        (KnowledgeSnippet(id="only-med", title="Med", text="medication dose", tags=["med"]),)
    )
    # A routine event shares no tokens with a medication guideline.
    assert KnowledgeAgent(kb).advise(_event(event_type="routine", response="")) is None


def test_azure_kb_placeholder_raises() -> None:
    with pytest.raises(NotImplementedError):
        AzureSearchKnowledgeBase()


def test_knowledge_runs_in_deliberate_tier() -> None:
    from airacare_foundry.agents.deliberate import DeliberateTier, ThreadExecutor
    from airacare_foundry.orchestrator import CareOrchestrator
    from airacare_foundry.store.local import seeded_local_store

    tier = DeliberateTier(enabled=True, knowledge=KnowledgeAgent(), executor=ThreadExecutor())
    orch = CareOrchestrator(seeded_local_store(":memory:"), deliberate=tier)
    orch.report(_event())
    tier.join()

    assert len(tier.advice_log) == 1
    assert "Guideline for wander" in tier.advice_log[0].advice
