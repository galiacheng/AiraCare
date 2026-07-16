"""FH3 tests — Microsoft Agent Framework executor + Connected-Agent/tool adapter scaffolding.

Two layers:

- **Offline (always run):** the adapter descriptors (:func:`connected_agent_specs` /
  :func:`tool_specs`) and the executor's async-runtime drain semantics. The executor is built
  with ``require_sdk=False`` so its threading/asyncio contract is proven with **no** MAF install
  — the SDK gate is a separate concern tested below.
- **SDK-gated:** behaviour that depends on ``agent-framework`` being importable is skipped when
  the optional ``[agents]`` extra is absent, mirroring the cosmos integration gating so CI stays
  offline-green.
"""

from __future__ import annotations

import importlib
import threading

import pytest

from airacare_foundry.agents.agent_framework import (
    AgentFrameworkExecutor,
    AgentSpec,
    ToolSpec,
    agent_framework_available,
    build_workflow,
    connected_agent_specs,
    tool_specs,
)
from airacare_foundry.agents.deliberate import DeliberateExecutor

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
        "policy-learning",
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
def test_build_workflow_is_fh4_seam_when_sdk_present() -> None:
    # With the SDK present, the FH4 seam is reachable and explicitly not-yet-implemented.
    with pytest.raises(NotImplementedError, match="FH4"):
        build_workflow(model_endpoint="https://example/openai")


@pytest.mark.skipif(_HAS_SDK, reason="agent-framework installed; missing-SDK path not exercised")
def test_build_workflow_requires_sdk_when_missing() -> None:
    with pytest.raises(ImportError, match=r"\[agents\]"):
        build_workflow(model_endpoint="https://example/openai")
