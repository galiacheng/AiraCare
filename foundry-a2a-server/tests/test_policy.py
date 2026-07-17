"""PolicyStore + fetch_policy tests: versioned per-patient policy, served only when behind."""

from __future__ import annotations

import pytest

from airacare_foundry.contracts import DailyLivingEvent, EdgePolicyUpdate, utcnow
from airacare_foundry.orchestrator import CareOrchestrator
from airacare_foundry.store.base import BASE_POLICY_VERSION, PolicyStore, policy_version_for
from airacare_foundry.store.cosmos import CosmosPolicyStore
from airacare_foundry.store.local import LocalPolicyStore, seeded_local_store


def _wander_event(response: str = "unclear", patient_id: str = "p-001") -> DailyLivingEvent:
    return DailyLivingEvent(
        type="wander",
        confidence=0.9,
        timestamp=utcnow(),
        patient_id=patient_id,
        baseline_deviation=0.95,
        edge_assessed_level="L2",
        edge_action_taken="local_alert",
        context={"time_of_day": "night", "door_open": True, "response": response},
    )


def test_local_policy_store_round_trip_and_replace() -> None:
    store = LocalPolicyStore(":memory:")
    assert store.get("p-001") is None

    store.upsert(EdgePolicyUpdate(version=2, patient_id="p-001", wander_confidence=0.6))
    got = store.get("p-001")
    assert got is not None
    assert got.version == 2
    assert got.wander_confidence == pytest.approx(0.6)

    # Only the latest version is retained (replace, not append).
    store.upsert(EdgePolicyUpdate(version=3, patient_id="p-001", no_response_seconds=10.0))
    latest = store.get("p-001")
    assert latest.version == 3
    assert latest.no_response_seconds == pytest.approx(10.0)


def test_policy_version_for_defaults_to_base() -> None:
    store = LocalPolicyStore(":memory:")
    assert policy_version_for(store, "p-001") == BASE_POLICY_VERSION
    store.upsert(EdgePolicyUpdate(version=4, patient_id="p-001"))
    assert policy_version_for(store, "p-001") == 4


def test_local_policy_store_satisfies_protocol() -> None:
    assert isinstance(LocalPolicyStore(":memory:"), PolicyStore)


def test_fetch_policy_only_when_behind() -> None:
    policy_store = LocalPolicyStore(":memory:")
    policy_store.upsert(EdgePolicyUpdate(version=3, patient_id="p-001", wander_confidence=0.6))
    orch = CareOrchestrator(seeded_local_store(":memory:"), policy_store=policy_store)

    assert orch.fetch_policy("p-001", since_version=1).version == 3
    assert orch.fetch_policy("p-001", since_version=3) is None
    # Unknown patient -> nothing to fetch.
    assert orch.fetch_policy("ghost", since_version=1) is None


def test_report_piggybacks_stored_version() -> None:
    policy_store = LocalPolicyStore(":memory:")
    policy_store.upsert(EdgePolicyUpdate(version=5, patient_id="p-001"))
    orch = CareOrchestrator(seeded_local_store(":memory:"), policy_store=policy_store)

    assert orch.report(_wander_event()).policy_version == 5


def test_report_piggybacks_base_version_when_no_policy() -> None:
    orch = CareOrchestrator(seeded_local_store(":memory:"))
    assert orch.report(_wander_event()).policy_version == BASE_POLICY_VERSION


def test_cosmos_policy_store_declares_protocol_methods() -> None:
    # Real (lazy-SDK) Cosmos impl of the same PolicyStore protocol as the local store.
    assert callable(CosmosPolicyStore.get)
    assert callable(CosmosPolicyStore.upsert)
