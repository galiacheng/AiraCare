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
from airacare_foundry.store.base import EventStore, PatientStateStore

_HAS_COSMOS = importlib.util.find_spec("azure.cosmos") is not None


def test_cosmos_classes_declare_protocol_methods() -> None:
    # Structural conformance without constructing (which needs the SDK + an account).
    assert callable(cosmos_mod.CosmosPatientStateStore.get)
    assert callable(cosmos_mod.CosmosPatientStateStore.upsert)
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


def test_resolve_endpoint_and_database_expand_env(monkeypatch) -> None:
    # Container deploys keep a generic baked-in config and inject values via the environment.
    monkeypatch.setenv("AIRACARE_COSMOS_ENDPOINT", "https://acct.documents.azure.com:443/")
    monkeypatch.setenv("AIRACARE_COSMOS_DATABASE", "airacare")
    sc = StoreConfig(
        backend="cosmos",
        cosmos_endpoint="${AIRACARE_COSMOS_ENDPOINT}",
        cosmos_database="${AIRACARE_COSMOS_DATABASE}",
        cosmos_auth="aad",
    )
    assert sc.resolve_endpoint() == "https://acct.documents.azure.com:443/"
    assert sc.resolve_database() == "airacare"


def test_resolve_endpoint_passthrough_and_database_default(monkeypatch) -> None:
    monkeypatch.delenv("AIRACARE_MISSING_EP", raising=False)
    # A plain value is returned unchanged; an unset ${VAR} endpoint resolves to None.
    assert StoreConfig(cosmos_endpoint="https://plain/").resolve_endpoint() == "https://plain/"
    assert StoreConfig(cosmos_endpoint="${AIRACARE_MISSING_EP}").resolve_endpoint() is None
    # An unset ${VAR} database falls back to the default name rather than empty.
    assert StoreConfig(cosmos_database="${AIRACARE_MISSING_EP}").resolve_database() == "airacare"


def test_aad_backend_needs_only_endpoint(monkeypatch) -> None:
    # With AAD auth, a missing credential is fine; only the endpoint is required. Build fails
    # later at SDK import time (no [cosmos] extra), not on the endpoint/credential guard.
    monkeypatch.setenv("AIRACARE_COSMOS_ENDPOINT", "https://acct.documents.azure.com:443/")
    config = _cosmos_config(
        cosmos_endpoint="${AIRACARE_COSMOS_ENDPOINT}", cosmos_auth="aad"
    )
    if _HAS_COSMOS:
        pytest.skip("azure.cosmos installed; would attempt a real client build")
    with pytest.raises(RuntimeError, match=r"\[cosmos\] extra"):
        _build_stores(config)


def test_local_backend_still_builds_both_stores() -> None:
    config = FoundryConfig(patient=PatientConfig(id="p-001", name="Grandpa Zhang"))
    state, events = _build_stores(config)
    assert isinstance(state, PatientStateStore)
    assert isinstance(events, EventStore)
    assert state.get("p-001") is not None  # seeded flagship patient
