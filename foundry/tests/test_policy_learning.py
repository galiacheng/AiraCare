"""Policy-Learning tests: recurring nighttime wanders distill a new versioned edge policy.

The learning runs in the deliberate tier (T2) and must never affect the synchronous T1
response — the new policy only surfaces on a *later* report's ``policy_version`` piggyback.
"""

from __future__ import annotations

import pytest

from airacare_foundry.agents.deliberate import DeliberateTier
from airacare_foundry.agents.policy_learning import PolicyLearningAgent
from airacare_foundry.config import DeliberateConfig, FoundryConfig, PatientConfig
from airacare_foundry.contracts import DailyLivingEvent, utcnow
from airacare_foundry.orchestrator import CareOrchestrator
from airacare_foundry.store.base import BASE_POLICY_VERSION, PatientState
from airacare_foundry.store.local import LocalPolicyStore, seeded_local_store


def _night_wander(patient_id: str = "p-001") -> DailyLivingEvent:
    return DailyLivingEvent(
        type="wander",
        confidence=0.9,
        timestamp=utcnow(),
        patient_id=patient_id,
        baseline_deviation=0.95,
        edge_assessed_level="L2",
        edge_action_taken="local_alert",
        context={"time_of_day": "night", "door_open": True, "response": "unclear"},
    )


def test_learns_after_threshold_and_bumps_version_once() -> None:
    store = LocalPolicyStore(":memory:")
    agent = PolicyLearningAgent(store, enabled=True)
    state = PatientState(patient_id="p-001", name="Grandpa Zhang", disease_stage="moderate")

    # Below threshold -> no policy learned yet.
    assert agent.observe(_night_wander(), state) is None
    assert agent.observe(_night_wander(), state) is None

    # Crossing the threshold distills a tuned policy and bumps the version.
    learned = agent.observe(_night_wander(), state)
    assert learned is not None
    assert learned.version == BASE_POLICY_VERSION + 1
    assert learned.wander_confidence == pytest.approx(0.6)
    assert "Grandpa Zhang" in learned.reassure_prompt
    assert store.get("p-001").version == learned.version

    # Emits exactly once — subsequent recurrences do not churn the version.
    assert agent.observe(_night_wander(), state) is None
    assert store.get("p-001").version == BASE_POLICY_VERSION + 1


def test_only_nighttime_wanders_count() -> None:
    store = LocalPolicyStore(":memory:")
    agent = PolicyLearningAgent(store, enabled=True)

    daytime = _night_wander()
    daytime.context["time_of_day"] = "day"
    for _ in range(5):
        assert agent.observe(daytime) is None
    assert store.get("p-001") is None


def test_disabled_agent_is_noop() -> None:
    store = LocalPolicyStore(":memory:")
    agent = PolicyLearningAgent(store, enabled=False)
    for _ in range(5):
        assert agent.observe(_night_wander()) is None
    assert store.get("p-001") is None


def test_learned_policy_surfaces_on_next_report() -> None:
    policy_store = LocalPolicyStore(":memory:")
    learning = PolicyLearningAgent(policy_store, enabled=True)
    deliberate = DeliberateTier(enabled=True, policy_learning=learning)
    orch = CareOrchestrator(
        seeded_local_store(":memory:"), deliberate=deliberate, policy_store=policy_store
    )

    # First two reports: still on the base policy version.
    assert orch.report(_night_wander()).policy_version == BASE_POLICY_VERSION
    assert orch.report(_night_wander()).policy_version == BASE_POLICY_VERSION
    # The third report triggers learning *after* its response is built, so it still
    # piggybacks the old version...
    assert orch.report(_night_wander()).policy_version == BASE_POLICY_VERSION
    # ...but the newly learned policy now surfaces on the next report and via fetch_policy.
    assert orch.report(_night_wander()).policy_version == BASE_POLICY_VERSION + 1
    pulled = orch.fetch_policy("p-001", since_version=BASE_POLICY_VERSION)
    assert pulled is not None
    assert pulled.wander_confidence == pytest.approx(0.6)


def test_from_config_wires_policy_learning_when_deliberate_enabled() -> None:
    config = FoundryConfig(
        patient=PatientConfig(id="p-001", name="Grandpa Zhang", disease_stage="moderate"),
        deliberate=DeliberateConfig(enabled=True),
    )
    orch = CareOrchestrator.from_config(config)
    for _ in range(3):
        orch.report(_night_wander())
    # After three nighttime wanders the config-built orchestrator has learned a new policy.
    assert orch.fetch_policy("p-001", since_version=BASE_POLICY_VERSION).version == BASE_POLICY_VERSION + 1
