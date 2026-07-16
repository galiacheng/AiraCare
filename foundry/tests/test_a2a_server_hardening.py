"""FH1 hardening tests: async executor selection + server health/auth/drain.

These cover the graduation seams for hosting the orchestrator as a real agent:
- ``deliberate.executor`` selects inline vs. background (thread) T2 execution;
- the A2A server exposes an unauthenticated ``/healthz`` probe;
- an optional bearer token gates the JSON-RPC POST endpoint;
- server shutdown drains in-flight deliberate (T2) jobs so nothing is lost.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from airacare_foundry.a2a_server import REPORT_METHOD, FoundryA2AServer
from airacare_foundry.agents.deliberate import InlineExecutor, ThreadExecutor
from airacare_foundry.config import DeliberateConfig, FoundryConfig
from airacare_foundry.contracts import DailyLivingEvent, utcnow
from airacare_foundry.orchestrator import CareOrchestrator, _build_executor


def _wander_event(level: str = "L3", action: str = "escalated", response: str = "no_response"):
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


def _call(endpoint: str, method: str, params: dict, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = {"jsonrpc": "2.0", "id": 7, "method": method, "params": params}
    request = urllib.request.Request(
        endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read())


def _report(endpoint: str, event: DailyLivingEvent, token: str | None = None) -> dict:
    return _call(endpoint, REPORT_METHOD, {"event": json.loads(event.model_dump_json())}, token)


def _base_url(server: FoundryA2AServer) -> str:
    return f"http://{server.host}:{server.port}"


def _thread_config() -> FoundryConfig:
    return FoundryConfig.model_validate(
        {
            "patient": {"id": "p-001", "name": "Grandpa Zhang"},
            "deliberate": {"enabled": True, "executor": "thread"},
        }
    )


# ---- executor selection -------------------------------------------------------------------


def test_default_executor_is_inline() -> None:
    assert DeliberateConfig().executor == "inline"


def test_build_executor_mapping() -> None:
    assert isinstance(_build_executor("inline"), InlineExecutor)
    assert isinstance(_build_executor("thread"), ThreadExecutor)


def test_build_executor_agents_requires_sdk() -> None:
    # FH3: 'agents' now maps to the Microsoft Agent Framework executor. Without the [agents]
    # extra installed it must fail fast with a clear, actionable install error (not silently
    # fall back). When the SDK is present it builds the real executor.
    from airacare_foundry.agents.agent_framework import (
        AgentFrameworkExecutor,
        agent_framework_available,
    )

    if agent_framework_available():
        executor = _build_executor("agents")
        assert isinstance(executor, AgentFrameworkExecutor)
        executor.close()
    else:
        with pytest.raises(ImportError, match=r"\[agents\]"):
            _build_executor("agents")


def test_from_config_wires_thread_executor() -> None:
    orch = CareOrchestrator.from_config(_thread_config())
    assert isinstance(orch._deliberate._executor, ThreadExecutor)


def test_thread_executor_returns_before_job_completes() -> None:
    """`report` off the safety path: submit returns while the job is still blocked."""
    executor = ThreadExecutor()
    release = threading.Event()
    done = threading.Event()

    def job() -> None:
        release.wait(5)
        done.set()

    executor.submit(job)
    assert not done.is_set()  # submit did not block on the job
    release.set()
    executor.join()
    assert done.is_set()


# ---- health probe -------------------------------------------------------------------------


def test_healthz_ok_and_unauthenticated() -> None:
    # Even with a token required for POST, the health probe stays open.
    with FoundryA2AServer(port=0, token="s3cret") as server:
        with urllib.request.urlopen(_base_url(server) + "/healthz", timeout=5) as response:
            assert response.status == 200
            assert json.loads(response.read())["status"] == "ok"


# ---- bearer auth --------------------------------------------------------------------------


def test_post_without_token_is_unauthorized() -> None:
    with FoundryA2AServer(port=0, token="s3cret") as server:
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _report(server.endpoint, _wander_event())
    assert exc_info.value.code == 401


def test_post_with_wrong_token_is_unauthorized() -> None:
    with FoundryA2AServer(port=0, token="s3cret") as server:
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _report(server.endpoint, _wander_event(), token="nope")
    assert exc_info.value.code == 401


def test_post_with_correct_token_succeeds() -> None:
    with FoundryA2AServer(port=0, token="s3cret") as server:
        body = _report(server.endpoint, _wander_event(), token="s3cret")
    assert body["result"]["considered_level"] == "L3"


def test_open_endpoint_when_no_token() -> None:
    with FoundryA2AServer(port=0) as server:
        assert server.auth_required is False
        body = _report(server.endpoint, _wander_event())
    assert body["result"]["considered_level"] == "L3"


# ---- graceful drain -----------------------------------------------------------------------


def test_shutdown_drains_inflight_deliberate_jobs() -> None:
    orch = CareOrchestrator.from_config(_thread_config())
    with FoundryA2AServer(orch, port=0) as server:
        _report(server.endpoint, _wander_event())
    # Context exit -> server.shutdown() -> orch.drain() awaits the background T2 job,
    # which files the scrubbed event to the store.
    assert len(orch._event_store.list_for_patient("p-001")) >= 1
