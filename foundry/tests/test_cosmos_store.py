"""Cosmos store tests — production graduation seam (no live account needed).

These verify the seam is correct *structurally*: the Cosmos stores implement the same protocols
as the local ones, construct a real client from config, and fail loudly with a clear message
when the optional ``azure-cosmos`` SDK is missing. Live round-trips are covered by the local
store tests (identical protocols) and the production run-book (``docs/production.md``).
"""

from __future__ import annotations

import builtins
import importlib.util

import pytest

from airacare_foundry.config import FoundryConfig, PatientConfig, StoreConfig
from airacare_foundry.orchestrator import _build_stores
from airacare_foundry.store import cosmos as cosmos_mod
from airacare_foundry.store.base import EventStore, PatientStateStore, PolicyStore

_HAS_COSMOS = importlib.util.find_spec("azure.cosmos") is not None


def test_cosmos_classes_declare_protocol_methods() -> None:
    # Structural conformance without constructing (which needs the SDK + an account).
    assert callable(cosmos_mod.CosmosPatientStateStore.get)
    assert callable(cosmos_mod.CosmosPatientStateStore.upsert)
    assert callable(cosmos_mod.CosmosPolicyStore.get)
    assert callable(cosmos_mod.CosmosPolicyStore.upsert)
    assert callable(cosmos_mod.CosmosEventStore.append)
    assert callable(cosmos_mod.CosmosEventStore.list_for_patient)


def test_partition_key_is_patient_id() -> None:
    assert cosmos_mod.PARTITION_KEY_PATH == "/patient_id"


@pytest.mark.skipif(_HAS_COSMOS, reason="azure-cosmos is installed; missing-SDK path not hit")
def test_missing_sdk_raises_actionable_error(monkeypatch) -> None:
    real_import = builtins.__import__

    def _no_cosmos(name, *args, **kwargs):
        if name.startswith("azure.cosmos"):
            raise ImportError("no azure.cosmos")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_cosmos)
    with pytest.raises(RuntimeError, match=r"\[cosmos\] extra"):
        cosmos_mod.CosmosPatientStateStore("https://x/", "key")


def _cosmos_config(**store_overrides) -> FoundryConfig:
    return FoundryConfig(
        patient=PatientConfig(id="p-001", name="Grandpa Zhang"),
        store=StoreConfig(backend="cosmos", **store_overrides),
    )


def test_cosmos_backend_requires_endpoint_and_credential() -> None:
    with pytest.raises(ValueError, match="cosmos_endpoint"):
        _build_stores(_cosmos_config())  # no endpoint/credential


def test_local_backend_still_builds_all_three_stores() -> None:
    config = FoundryConfig(patient=PatientConfig(id="p-001", name="Grandpa Zhang"))
    state, policy, events = _build_stores(config)
    assert isinstance(state, PatientStateStore)
    assert isinstance(policy, PolicyStore)
    assert isinstance(events, EventStore)
    assert state.get("p-001") is not None  # seeded flagship patient
