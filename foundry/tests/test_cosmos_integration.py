"""Cosmos live integration tests — opt-in, real round-trips against a Cosmos endpoint.

Skipped unless ``AIRACARE_COSMOS_ENDPOINT`` is set, so CI/offline runs stay green. Point it at
the local **Azure Cosmos DB Emulator** (self-signed cert → set ``AIRACARE_COSMOS_TLS_VERIFY=0``)
or a real account. These prove the three Cosmos stores actually persist and query correctly —
the piece the structural tests (``test_cosmos_store.py``) cannot cover.

Emulator quickstart (Docker):

    docker run -d --name airacare-cosmos -p 8081:8081 -p 10250-10255:10250-10255 \
        mcr.microsoft.com/cosmosdb/linux/azure-cosmos-emulator:latest

    $env:AIRACARE_COSMOS_ENDPOINT = "https://localhost:8081/"
    $env:AIRACARE_COSMOS_KEY = "C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw=="
    $env:AIRACARE_COSMOS_TLS_VERIFY = "0"
    python -m pytest tests/test_cosmos_integration.py -q
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest

_ENDPOINT = os.environ.get("AIRACARE_COSMOS_ENDPOINT")

pytestmark = pytest.mark.skipif(
    not _ENDPOINT, reason="set AIRACARE_COSMOS_ENDPOINT to run live Cosmos integration tests"
)

# Well-known emulator key is the default; a real account overrides via AIRACARE_COSMOS_KEY.
_KEY = os.environ.get(
    "AIRACARE_COSMOS_KEY",
    "C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw==",
)
_TLS = os.environ.get("AIRACARE_COSMOS_TLS_VERIFY", "1") not in ("0", "false", "False")
# Isolate each run in its own database so repeated runs never collide.
_DB = f"airacare_it_{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def stores():
    from airacare_foundry.store.cosmos import (
        CosmosEventStore,
        CosmosPatientStateStore,
        CosmosPolicyStore,
    )

    kw = {"database": _DB, "auth": "key", "tls_verify": _TLS}
    state = CosmosPatientStateStore(_ENDPOINT, _KEY, **kw)
    policy = CosmosPolicyStore(_ENDPOINT, _KEY, **kw)
    events = CosmosEventStore(_ENDPOINT, _KEY, **kw)
    yield state, policy, events


def test_patient_state_roundtrip(stores):
    from airacare_foundry.store.base import PatientState

    state, _, _ = stores
    assert state.get("p-live") is None
    state.upsert(PatientState(patient_id="p-live", name="Live Test", disease_stage="severe"))
    got = state.get("p-live")
    assert got is not None
    assert got.name == "Live Test"
    assert got.disease_stage == "severe"


def test_policy_version_gate(stores):
    from airacare_foundry.contracts import EdgePolicyUpdate

    _, policy, _ = stores
    assert policy.get("p-live") is None
    policy.upsert(EdgePolicyUpdate(version=5, patient_id="p-live", wander_confidence=0.6))
    got = policy.get("p-live")
    assert got is not None and got.version == 5


def test_event_append_and_range_query(stores):
    from airacare_foundry.contracts import DailyLivingEvent
    from airacare_foundry.store.base import RecordedEvent

    _, _, events = stores
    base = datetime(2026, 7, 1, tzinfo=timezone.utc)
    for day in range(5):
        ev = DailyLivingEvent(
            type="routine",
            confidence=0.5,
            timestamp=base.replace(day=1 + day),
            patient_id="p-range",
            baseline_deviation=0.1,
        )
        events.append(RecordedEvent(event=ev, considered_level="L1"))

    all_five = events.list_for_patient("p-range")
    assert len(all_five) == 5
    # ascending by ts
    ts = [r.event.timestamp for r in all_five]
    assert ts == sorted(ts)
    # since inclusive / until exclusive
    window = events.list_for_patient(
        "p-range",
        since=base.replace(day=2),
        until=base.replace(day=4),
    )
    assert [r.event.timestamp.day for r in window] == [2, 3]


def test_orchestrator_trend_over_cosmos(stores):
    """End-to-end: seed the demo history into Cosmos and read a declining trend back."""
    from airacare_foundry.agents.cognitive_trend import CognitiveTrendAgent
    from airacare_foundry.tools.demo_seed import generate_events, to_records

    _, _, events = stores
    pid = "p-trend"
    for rec in to_records(generate_events(patient_id=pid)):
        events.append(rec)
    trend = CognitiveTrendAgent(events).analyze(pid)
    assert trend.direction == "declining"
