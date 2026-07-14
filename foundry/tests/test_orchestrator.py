"""Orchestrator tests: reflex assessment via the store-backed policy + config + policy."""

from __future__ import annotations

from airacare_foundry.agents.deliberate import DeliberateTier
from airacare_foundry.config import FoundryConfig, PatientConfig
from airacare_foundry.contracts import DailyLivingEvent, EdgePolicyUpdate, utcnow
from airacare_foundry.orchestrator import CareOrchestrator, default_orchestrator


def _wander_event(level: str, action: str, response: str, patient_id: str = "p-001") -> DailyLivingEvent:
    return DailyLivingEvent(
        type="wander",
        confidence=0.9,
        timestamp=utcnow(),
        patient_id=patient_id,
        baseline_deviation=0.95,
        edge_assessed_level=level,  # type: ignore[arg-type]
        edge_action_taken=action,  # type: ignore[arg-type]
        context={"time_of_day": "night", "door_open": True, "response": response},
    )


def test_default_orchestrator_assesses_flagship() -> None:
    orch = default_orchestrator()
    assert orch.report(_wander_event("L3", "escalated", "no_response")).considered_level == "L3"
    assert orch.report(_wander_event("L1", "reassured", "ok")).considered_level == "L1"


def test_unknown_patient_falls_back_to_safe_default() -> None:
    orch = default_orchestrator()
    # No stored state for this patient -> safe default (moderate) still assesses correctly.
    event = _wander_event("L3", "escalated", "no_response", patient_id="ghost")
    assert orch.report(event).considered_level == "L3"


def test_deliberate_tier_scheduled_when_enabled() -> None:
    from airacare_foundry.store.local import seeded_local_store

    tier = DeliberateTier(enabled=True)
    orch = CareOrchestrator(seeded_local_store(":memory:"), deliberate=tier)
    orch.report(_wander_event("L1", "reassured", "ok"))
    assert tier.scheduled == ["p-001"]


def test_fetch_policy_piggyback() -> None:
    from airacare_foundry.store.local import seeded_local_store

    policy = EdgePolicyUpdate(version=2, patient_id="p-001", no_response_seconds=6.0)
    orch = CareOrchestrator(seeded_local_store(":memory:"), policy=policy)

    # report() stamps the current policy version so the edge knows to pull.
    assessment = orch.report(_wander_event("L2", "local_alert", "unclear"))
    assert assessment.policy_version == 2
    # Edge behind -> gets policy; edge current -> None.
    assert orch.fetch_policy("p-001", since_version=1).version == 2
    assert orch.fetch_policy("p-001", since_version=2) is None


def test_from_config_builds_local_store() -> None:
    config = FoundryConfig(patient=PatientConfig(id="p-001", name="Grandpa Zhang"))
    orch = CareOrchestrator.from_config(config)
    assert orch.report(_wander_event("L2", "local_alert", "unclear")).considered_level == "L2"
