"""Local patient-state store tests: seed, round-trip, upsert, miss, cosmos placeholder."""

from __future__ import annotations

import pytest

from airacare_foundry.store.base import PatientState
from airacare_foundry.store.cosmos import CosmosPatientStateStore
from airacare_foundry.store.local import LocalPatientStateStore, seeded_local_store


def test_seeded_store_has_flagship_patient() -> None:
    store = seeded_local_store(":memory:")
    state = store.get("p-001")
    assert state is not None
    assert state.disease_stage == "moderate"
    assert state.name == "Grandpa Zhang"


def test_get_unknown_patient_returns_none() -> None:
    store = LocalPatientStateStore(":memory:")
    assert store.get("does-not-exist") is None


def test_upsert_inserts_then_updates() -> None:
    store = LocalPatientStateStore(":memory:")
    store.upsert(PatientState(patient_id="p-002", name="Ada", disease_stage="mild"))
    assert store.get("p-002").disease_stage == "mild"

    store.upsert(
        PatientState(
            patient_id="p-002", name="Ada", disease_stage="severe", baseline_deviation=0.4
        )
    )
    updated = store.get("p-002")
    assert updated.disease_stage == "severe"
    assert updated.baseline_deviation == pytest.approx(0.4)


def test_satisfies_store_protocol() -> None:
    from airacare_foundry.store.base import PatientStateStore

    assert isinstance(LocalPatientStateStore(":memory:"), PatientStateStore)


def test_cosmos_placeholder_raises() -> None:
    with pytest.raises(NotImplementedError):
        CosmosPatientStateStore()
