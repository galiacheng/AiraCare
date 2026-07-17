"""FH3/FH6 tests — Microsoft Agent Framework executor, Connected-Agent adapters, and the live
advisory workflow (build_workflow / CareWorkflow / case_file) wiring.

Two layers:

- **Offline (always run):** the adapter descriptors (:func:`connected_agent_specs` /
  :func:`tool_specs`), the executor's async-runtime drain semantics, the scrubbed
  :func:`case_file` builder (incl. the privacy invariant), the ``deliberate.*`` model-binding
  config resolvers, and the :class:`DeliberateTier` narrator wiring (best-effort, no MAF/model).
  The executor is built with ``require_sdk=False`` so its threading/asyncio contract is proven
  with **no** MAF install — the SDK gate is a separate concern tested below.
- **SDK-gated:** behaviour that depends on ``agent-framework`` being importable (``build_workflow``
  returning a live :class:`CareWorkflow`) is skipped when the optional ``[agents]`` extra is
  absent, mirroring the cosmos integration gating so CI stays offline-green.
"""

from __future__ import annotations

import importlib
import threading

import pytest

from airacare_foundry.agents.agent_framework import (
    AgentFrameworkExecutor,
    AgentSpec,
    CareWorkflow,
    ToolSpec,
    agent_framework_available,
    build_workflow,
    case_file,
    connected_agent_specs,
    tool_specs,
)
from airacare_foundry.agents.deliberate import DeliberateExecutor, DeliberateTier
from airacare_foundry.config import DeliberateConfig, FoundryConfig, PatientConfig
from airacare_foundry.contracts import CloudAssessment, DailyLivingEvent, utcnow
from airacare_foundry.orchestrator import _build_narrator

_HAS_SDK = agent_framework_available()


def _resolve(dotted: str) -> object:
    module_path, _, attr = dotted.rpartition(".")
    module = importlib.import_module(module_path)
    return getattr(module, attr)


# -- Adapter scaffolding (offline) -----------------------------------------------------------


def test_connected_agent_specs_topology() -> None:
    specs = connected_agent_specs()
    assert [s.name for s in specs] == [
        "risk-reasoning",
        "knowledge",
        "escalation",
        "cognitive-trend",
        "briefing",
    ]
    for spec in specs:
        assert isinstance(spec, AgentSpec)
        assert spec.role and spec.instructions
        # The wrapped class must actually exist — scaffolding stays honest as code evolves.
        assert isinstance(_resolve(spec.wraps), type)


def test_tool_specs_topology() -> None:
    tools = tool_specs()
    assert [t.name for t in tools] == ["notify", "geofence", "escalation-timer"]
    for tool in tools:
        assert isinstance(tool, ToolSpec)
        assert tool.description
        assert _resolve(tool.wraps) is not None


# -- Executor async-runtime contract (offline; require_sdk=False) ----------------------------


def test_executor_satisfies_protocol() -> None:
    executor = AgentFrameworkExecutor(require_sdk=False)
    try:
        assert isinstance(executor, DeliberateExecutor)
    finally:
        executor.close()


def test_executor_runs_and_drains() -> None:
    executor = AgentFrameworkExecutor(require_sdk=False)
    lock = threading.Lock()
    ran: list[int] = []

    def make(i: int):
        def job() -> None:
            with lock:
                ran.append(i)

        return job

    try:
        for i in range(25):
            executor.submit(make(i))
        executor.join()  # must block until every scheduled job completed
        assert sorted(ran) == list(range(25))
    finally:
        executor.close()


def test_executor_swallows_job_failure() -> None:
    executor = AgentFrameworkExecutor(require_sdk=False)
    survived: list[str] = []

    def boom() -> None:
        raise RuntimeError("T2 blew up")

    try:
        executor.submit(boom)
        executor.submit(lambda: survived.append("ok"))
        executor.join()  # a failing T2 job must never surface on drain
        assert survived == ["ok"]
    finally:
        executor.close()


def test_executor_rejects_submit_after_close() -> None:
    executor = AgentFrameworkExecutor(require_sdk=False)
    executor.close()
    with pytest.raises(RuntimeError, match="closed"):
        executor.submit(lambda: None)


# -- SDK gate --------------------------------------------------------------------------------


@pytest.mark.skipif(_HAS_SDK, reason="agent-framework installed; missing-SDK path not exercised")
def test_require_sdk_raises_clear_error_when_missing() -> None:
    # Default construction requires the SDK and must point the user at the [agents] extra.
    with pytest.raises(ImportError, match=r"\[agents\]"):
        AgentFrameworkExecutor()


@pytest.mark.skipif(not _HAS_SDK, reason="requires the agent-framework [agents] extra")
def test_build_workflow_returns_careworkflow_when_sdk_present() -> None:
    # With the SDK present, build_workflow binds the six connected agents and returns a live
    # CareWorkflow. Construction makes no network call (the model is only reached at narrate()).
    workflow = build_workflow("https://example.cognitiveservices.azure.com/", "gpt-5.4")
    try:
        assert isinstance(workflow, CareWorkflow)
        assert workflow.specialist_names == [s.name for s in connected_agent_specs()]
    finally:
        workflow.close()


@pytest.mark.skipif(_HAS_SDK, reason="agent-framework installed; missing-SDK path not exercised")
def test_build_workflow_requires_sdk_when_missing() -> None:
    with pytest.raises(ImportError, match=r"\[agents\]"):
        build_workflow("https://example.cognitiveservices.azure.com/", "gpt-5.4")


# -- Scrubbed case-file builder (offline; the sole model input) ------------------------------


def _event(**over) -> DailyLivingEvent:
    base = dict(
        type="wander",
        confidence=0.82,
        timestamp=utcnow(),
        patient_id="p-001",
        features=[0.111, 0.222, 0.333],
        baseline_deviation=0.55,
        edge_assessed_level="L2",
        edge_action_taken="local_alert",
        context={"time_of_day": "night", "location": "exit"},
    )
    base.update(over)
    return DailyLivingEvent(**base)


def test_case_file_carries_fixed_facts() -> None:
    ev = _event()
    asmt = CloudAssessment(considered_level="L3", reason="severe-stage nighttime wander")
    text = case_file(ev, asmt, patient_name="Rose", state=None)
    assert "CONSIDERED LEVEL (authoritative): L3" in text
    assert "severe-stage nighttime wander" in text
    assert "Rose" in text
    assert "wander" in text
    assert "local_alert" in text
    # Context keys are surfaced (already crossed the boundary) but as keys, for the narrator.
    assert "time_of_day" in text


def test_case_file_prose_never_leaks_raw_features() -> None:
    ev = _event(features=[0.987654, 0.123456])
    text = case_file(ev, CloudAssessment(considered_level="L1", reason="ok"))
    # The human-readable prose (everything before the machine record block) may show only the
    # COUNT of voice-biomarker features — never the raw values.
    prose, _, record = text.partition("DAILY EVENT RECORD (JSON)")
    assert "features present: 2" in prose
    assert "0.987654" not in prose
    assert "0.123456" not in prose
    # The authoritative machine record the hosted agent persists DOES carry the derived features
    # (they already crossed the A2A wire and power the cloud cognitive-trajectory chart).
    assert record and "0.987654" in record


def test_case_file_without_record_is_prose_only() -> None:
    ev = _event(features=[0.987654])
    text = case_file(ev, CloudAssessment(considered_level="L1", reason="ok"), include_record=False)
    assert "DAILY EVENT RECORD" not in text
    assert "0.987654" not in text


def test_case_file_falls_back_to_edge_level_without_assessment() -> None:
    text = case_file(_event(edge_assessed_level="L2"), None)
    assert "CONSIDERED LEVEL (authoritative): L2" in text


# -- Config resolvers for the foundry model binding (offline) --------------------------------


def test_deliberate_config_resolves_env_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AF_TEST_ENDPOINT", "https://real.cognitiveservices.azure.com/")
    dc = DeliberateConfig(
        executor="agents",
        foundry_endpoint="${AF_TEST_ENDPOINT}",
        foundry_deployment="gpt-5.4",
    )
    assert dc.resolve_foundry_endpoint() == "https://real.cognitiveservices.azure.com/"
    assert dc.resolve_foundry_deployment() == "gpt-5.4"  # plain value returned as-is
    assert dc.foundry_api_version == "preview"


def test_deliberate_config_unset_model_binding_is_none() -> None:
    dc = DeliberateConfig()
    assert dc.resolve_foundry_endpoint() is None
    assert dc.resolve_foundry_deployment() is None


# -- Narrator wiring (offline; no MAF, no model call) ----------------------------------------


def _cfg(**deliberate) -> FoundryConfig:
    return FoundryConfig(
        patient=PatientConfig(id="p-001", name="Rose", disease_stage="severe"),
        deliberate=DeliberateConfig(**deliberate),
    )


def test_build_narrator_none_unless_agents_and_endpoint() -> None:
    # Default / non-agents executor -> no narrator (deterministic path, parity preserved).
    assert _build_narrator(_cfg()) is None
    assert _build_narrator(_cfg(executor="thread")) is None
    # 'agents' selected but no model endpoint -> still None (no model narrative).
    assert _build_narrator(_cfg(executor="agents")) is None
    assert _build_narrator(_cfg(executor="agents", foundry_deployment="gpt-5.4")) is None


def test_deliberate_tier_narrator_is_best_effort() -> None:
    # A narrator that raises must be swallowed; the deterministic agents already ran.
    tier = DeliberateTier(enabled=True, narrator=lambda *_: (_ for _ in ()).throw(RuntimeError()))
    tier.schedule(_event())
    tier.join()
    assert tier.narrative_log == []


def test_deliberate_tier_records_narrative() -> None:
    tier = DeliberateTier(enabled=True, narrator=lambda ev, st, asmt: f"briefing for {ev.patient_id}")
    tier.schedule(_event(), None, CloudAssessment(considered_level="L3", reason="r"))
    tier.join()
    assert tier.narrative_log == ["briefing for p-001"]
