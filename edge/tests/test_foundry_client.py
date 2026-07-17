"""Offline tests for the standard-A2A Foundry client.

No network: ``urllib.request.urlopen`` is monkeypatched with a fake A2A transport that dispatches
on the JSON-RPC ``method`` field, so we exercise the real ``message/send`` -> ``tasks/get`` poll ->
``CONSIDERED ASSESSMENT (JSON)`` parse path deterministically.
"""

from __future__ import annotations

import json
import urllib.error

from airacare_edge.cloud.contracts import CloudAction, CloudAssessment, DailyLivingEvent, utcnow
from airacare_edge.cloud.foundry_client import (
    ASSESSMENT_MARKER,
    DAILY_EVENT_MARKER,
    FoundryA2AClient,
    build_daily_event_message,
    parse_assessment_block,
)

ENDPOINT = "https://cog.example.services.ai.azure.com/api/projects/p/agents/a/endpoint/protocols/a2a"


def _event(response: str = "unclear") -> DailyLivingEvent:
    return DailyLivingEvent(
        type="wander",
        confidence=0.9,
        timestamp=utcnow(),
        patient_id="p-001",
        baseline_deviation=0.95,
        edge_assessed_level="L2",
        edge_action_taken="local_alert",
        context={"time_of_day": "night", "door_open": True, "response": response},
    )


def _assessment_block(level: str = "L2") -> str:
    assessment = CloudAssessment(
        considered_level=level,
        reason=f"considered {level} for wander",
        caregiver_notifications=[CloudAction(channel="family", message="Please check on the patient.")],
        policy_version=1,
    )
    return f"{ASSESSMENT_MARKER}\n{assessment.model_dump_json()}"


def _text_artifact(text: str) -> dict:
    return {"parts": [{"kind": "text", "text": text}]}


class _FakeResp:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class _FakeTransport:
    """Dispatches on JSON-RPC method; each method maps to a body or a queue of bodies."""

    def __init__(self, responses: dict) -> None:
        self._responses = responses
        self.requests: list[dict] = []

    def __call__(self, request, timeout=None):  # noqa: ANN001 - urllib.request.Request
        payload = json.loads(request.data.decode("utf-8"))
        self.requests.append(payload)
        entry = self._responses[payload["method"]]
        body = entry.pop(0) if isinstance(entry, list) else entry
        return _FakeResp(json.dumps(body).encode("utf-8"))


def _rpc_result(result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": "1", "result": result}


def _install(monkeypatch, transport: _FakeTransport) -> None:
    monkeypatch.setattr("airacare_edge.cloud.foundry_client.urllib.request.urlopen", transport)


# --- message builder + parser -------------------------------------------------
def test_build_daily_event_message_roundtrips_record():
    text = build_daily_event_message(_event())
    assert DAILY_EVENT_MARKER in text
    brace = text.find("{")
    record = json.loads(text[brace:])
    assert record["event"]["patient_id"] == "p-001"
    assert record["event"]["type"] == "wander"


def test_parse_assessment_block_extracts_and_ignores_plain_text():
    got = parse_assessment_block("some warm recap\n" + _assessment_block("L3"))
    assert got is not None and got.considered_level == "L3"
    assert parse_assessment_block("just a friendly recap, no block here") is None


# --- report(): async task poll happy path ------------------------------------
def test_report_polls_task_and_parses_assessment(monkeypatch):
    transport = _FakeTransport(
        {
            "message/send": _rpc_result(
                {"kind": "task", "id": "t1", "status": {"state": "working"}, "artifacts": []}
            ),
            "tasks/get": _rpc_result(
                {
                    "kind": "task",
                    "id": "t1",
                    "status": {"state": "completed"},
                    "artifacts": [
                        _text_artifact("Brief recap for the family..."),
                        _text_artifact(_assessment_block("L2")),
                    ],
                    "history": [],
                }
            ),
        }
    )
    _install(monkeypatch, transport)
    client = FoundryA2AClient(ENDPOINT, token="fake-token", poll_interval=0.0)
    assessment = client.report(_event())
    assert assessment is not None
    assert assessment.considered_level == "L2"
    assert any(a.channel == "family" for a in assessment.caregiver_notifications)
    # message/send carried the forwarded record; a bearer token was attached.
    assert transport.requests[0]["method"] == "message/send"
    assert DAILY_EVENT_MARKER in transport.requests[0]["params"]["message"]["parts"][0]["text"]


# --- report(): synchronous message result (no task) --------------------------
def test_report_handles_synchronous_message(monkeypatch):
    transport = _FakeTransport(
        {
            "message/send": _rpc_result(
                {"kind": "message", "parts": [{"kind": "text", "text": _assessment_block("L1")}]}
            )
        }
    )
    _install(monkeypatch, transport)
    client = FoundryA2AClient(ENDPOINT, token="fake-token", poll_interval=0.0)
    assessment = client.report(_event("ok"))
    assert assessment is not None and assessment.considered_level == "L1"
    assert [r["method"] for r in transport.requests] == ["message/send"]  # no polling needed


# --- report(): failure paths all return None (offline-safe) ------------------
def test_report_offline_returns_none(monkeypatch):
    def _boom(request, timeout=None):  # noqa: ANN001
        raise urllib.error.URLError("unreachable")

    _install(monkeypatch, _FakeTransport({}))
    monkeypatch.setattr("airacare_edge.cloud.foundry_client.urllib.request.urlopen", _boom)
    client = FoundryA2AClient(ENDPOINT, token="fake-token", poll_interval=0.0)
    assert client.report(_event()) is None


def test_report_jsonrpc_error_returns_none(monkeypatch):
    transport = _FakeTransport(
        {"message/send": {"jsonrpc": "2.0", "id": "1", "error": {"code": -32601, "message": "no"}}}
    )
    _install(monkeypatch, transport)
    client = FoundryA2AClient(ENDPOINT, token="fake-token", poll_interval=0.0)
    assert client.report(_event()) is None


def test_report_without_assessment_block_returns_none(monkeypatch):
    transport = _FakeTransport(
        {
            "message/send": _rpc_result(
                {
                    "kind": "task",
                    "id": "t1",
                    "status": {"state": "completed"},
                    "artifacts": [_text_artifact("Just a warm recap, no structured block.")],
                }
            )
        }
    )
    _install(monkeypatch, transport)
    client = FoundryA2AClient(ENDPOINT, token="fake-token", poll_interval=0.0)
    assert client.report(_event()) is None


def test_report_poll_timeout_returns_none(monkeypatch):
    # Task never leaves "working"; a zero poll budget means we give up and (finding no block) None.
    transport = _FakeTransport(
        {
            "message/send": _rpc_result({"kind": "task", "id": "t1", "status": {"state": "working"}}),
            "tasks/get": _rpc_result({"kind": "task", "id": "t1", "status": {"state": "working"}}),
        }
    )
    _install(monkeypatch, transport)
    client = FoundryA2AClient(ENDPOINT, token="fake-token", poll_interval=0.0, poll_timeout=0.0)
    assert client.report(_event()) is None


# --- fetch_policy is a no-op in the standard-A2A topology ---------------------
def test_fetch_policy_returns_none():
    client = FoundryA2AClient(ENDPOINT, token="fake-token")
    assert client.fetch_policy("p-001", since_version=1) is None
