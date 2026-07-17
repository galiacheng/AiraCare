"""A2A server tests: the Foundry server speaks the edge's JSON-RPC contract over HTTP.

A raw urllib client exercises both wire methods (``airacare.report`` +
``airacare.fetch_policy``) with no edge dependency; a second test uses the edge's own
``A2AClient`` (skipped if edge isn't importable) to prove the drop-in works end-to-end —
the exact client the edge ships points at this server and gets a CloudAssessment.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from airacare_foundry.a2a_server import FETCH_POLICY_METHOD, REPORT_METHOD, FoundryA2AServer
from airacare_foundry.contracts import DailyLivingEvent, EdgePolicyUpdate, utcnow
from airacare_foundry.orchestrator import CareOrchestrator
from airacare_foundry.store.local import seeded_local_store


def _wander_event(level: str, action: str, response: str) -> DailyLivingEvent:
    return DailyLivingEvent(
        type="wander",
        confidence=0.9,
        timestamp=utcnow(),
        patient_id="p-001",
        baseline_deviation=0.95,
        edge_assessed_level=level,  # type: ignore[arg-type]
        edge_action_taken=action,  # type: ignore[arg-type]
        context={"time_of_day": "night", "door_open": True, "response": response},
    )


def _call(endpoint: str, method: str, params: dict) -> dict:
    payload = {"jsonrpc": "2.0", "id": 7, "method": method, "params": params}
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read())


def _report(endpoint: str, event: DailyLivingEvent) -> dict:
    return _call(endpoint, REPORT_METHOD, {"event": json.loads(event.model_dump_json())})


def test_report_roundtrip_l3() -> None:
    with FoundryA2AServer(port=0) as server:  # port 0 -> ephemeral free port
        body = _report(server.endpoint, _wander_event("L3", "escalated", "no_response"))
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == 7
    result = body["result"]
    assert result["considered_level"] == "L3"
    channels = {n["channel"] for n in result["caregiver_notifications"]}
    assert {"family", "community"} <= channels


def test_report_roundtrip_l1_no_notifications() -> None:
    with FoundryA2AServer(port=0) as server:
        body = _report(server.endpoint, _wander_event("L1", "reassured", "ok"))
    result = body["result"]
    assert result["considered_level"] == "L1"
    assert result["caregiver_notifications"] == []


def test_fetch_policy_returns_newer_version() -> None:
    policy = EdgePolicyUpdate(version=3, patient_id="p-001", wander_confidence=0.6)
    orch = CareOrchestrator(seeded_local_store(":memory:"), policy=policy)
    with FoundryA2AServer(orch, port=0) as server:
        # Edge is behind (v1) -> gets the new policy.
        newer = _call(server.endpoint, FETCH_POLICY_METHOD, {"patient_id": "p-001", "since_version": 1})
        # Edge already current (v3) -> nothing to fetch.
        current = _call(server.endpoint, FETCH_POLICY_METHOD, {"patient_id": "p-001", "since_version": 3})
    assert newer["result"]["version"] == 3
    assert current["result"] is None


def test_report_stamps_policy_version() -> None:
    policy = EdgePolicyUpdate(version=5, patient_id="p-001")
    orch = CareOrchestrator(seeded_local_store(":memory:"), policy=policy)
    with FoundryA2AServer(orch, port=0) as server:
        body = _report(server.endpoint, _wander_event("L2", "local_alert", "unclear"))
    assert body["result"]["policy_version"] == 5


def test_unknown_method_returns_error() -> None:
    with FoundryA2AServer(port=0) as server:
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _call(server.endpoint, "airacare.unknown", {})
    body = json.loads(exc_info.value.read())
    assert exc_info.value.code == 400
    assert "error" in body
    assert body.get("result") is None


def test_edge_a2a_client_drops_in() -> None:
    a2a_client = pytest.importorskip(
        "airacare_edge.cloud.a2a_client", reason="edge package not importable"
    )
    edge_contracts = pytest.importorskip("airacare_edge.cloud.contracts")

    event = edge_contracts.DailyLivingEvent(
        type="wander",
        confidence=0.9,
        timestamp=edge_contracts.utcnow(),
        patient_id="p-001",
        baseline_deviation=0.95,
        edge_assessed_level="L3",
        edge_action_taken="escalated",
        context={"time_of_day": "night", "door_open": True, "response": "no_response"},
    )

    with FoundryA2AServer(port=0) as server:
        client = a2a_client.A2AClient(server.endpoint)
        assessment = client.report(event)
        # No policy configured on the default orchestrator -> nothing newer to fetch.
        policy = client.fetch_policy("p-001", since_version=1)

    assert assessment is not None
    assert assessment.considered_level == "L3"
    assert any(n.channel == "family" for n in assessment.caregiver_notifications)
    assert policy is None
