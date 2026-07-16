"""FH3 — Microsoft Agent Framework (MAF) executor + Connected-Agent/tool adapter scaffolding.

This is the seam that graduates the asynchronous DELIBERATE tier (T2) from a plain background
worker onto the **Microsoft Agent Framework** runtime, selected by ``deliberate.executor: agents``.

Design intent (see foundry-design.md §5):

- :class:`AgentFrameworkExecutor` implements the same
  :class:`~airacare_foundry.agents.deliberate.DeliberateExecutor` protocol as ``InlineExecutor`` /
  ``ThreadExecutor``. Each fire-and-forget T2 job is scheduled on a dedicated asyncio event loop
  running on a background thread — the async substrate MAF itself builds on — so ``submit``
  returns immediately and ``join`` drains in-flight work. The wired Python agents
  (Policy-Learning, Escalation, Knowledge, event filing) run **unchanged**; no model call is made.

- The adapter scaffolding (:func:`connected_agent_specs`, :func:`tool_specs`) declares how the six
  Connected Agents and the Notify / Geofence / EscalationTimer tools map onto MAF agents/skills.
  These are pure descriptors (no MAF import, no model) so the offline demo/tests can introspect
  the planned topology. **FH4** binds them to a live Foundry model deployment via
  :func:`build_workflow`, which is intentionally left as a documented ``NotImplementedError`` seam
  until a model endpoint exists.

Discipline: ``agent-framework`` is a **lazy** optional import behind the ``[agents]`` extra — the
local ``inline`` / ``thread`` paths never need the SDK, mirroring the ``azure-cosmos`` pattern.
Constructing :class:`AgentFrameworkExecutor` without the SDK raises a clear, actionable error.
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Callable

__all__ = [
    "AgentFrameworkExecutor",
    "AgentSpec",
    "ToolSpec",
    "connected_agent_specs",
    "tool_specs",
    "build_workflow",
    "agent_framework_available",
]

_MISSING_SDK = (
    "deliberate.executor: 'agents' requires the Microsoft Agent Framework, which is not "
    "installed. Install the optional extra:  pip install -e \".[agents]\"  "
    "(pulls agent-framework). The local 'inline' and 'thread' executors need no extra."
)


def _require_agent_framework():
    """Lazily import the Microsoft Agent Framework or raise a clear ``[agents]``-extra error."""
    try:
        import agent_framework  # noqa: F401  (import name for the agent-framework distribution)
    except ImportError as exc:  # pragma: no cover - exercised only without the SDK
        raise ImportError(_MISSING_SDK) from exc
    return agent_framework


def agent_framework_available() -> bool:
    """True when the Microsoft Agent Framework SDK can be imported (for skip-gating tests)."""
    try:
        import agent_framework  # noqa: F401
    except ImportError:
        return False
    return True


class AgentFrameworkExecutor:
    """DeliberateExecutor that runs T2 jobs on an asyncio runtime (the MAF substrate).

    A dedicated daemon thread owns an asyncio event loop; each submitted job is scheduled as a
    coroutine, so :meth:`submit` returns immediately and :meth:`join` blocks until in-flight jobs
    finish. This satisfies the :class:`~airacare_foundry.agents.deliberate.DeliberateExecutor`
    protocol and is the seam FH4 upgrades to a full MAF ``WorkflowBuilder`` (see
    :func:`build_workflow`) once a Foundry model deployment is available.

    A T2 job failure is swallowed (logged as a best-effort) exactly like ``ThreadExecutor`` — the
    deliberate tier is off the safety path and must never crash the runtime.
    """

    def __init__(self, *, require_sdk: bool = True) -> None:
        # Fail fast with an actionable message when 'agents' is selected without the extra.
        if require_sdk:
            _require_agent_framework()
        self._loop = asyncio.new_event_loop()
        self._pending: set[Future] = set()
        self._lock = threading.Lock()
        self._closed = False
        self._thread = threading.Thread(
            target=self._run_loop, name="deliberate-af", daemon=True
        )
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def submit(self, job: Callable[[], None]) -> None:
        if self._closed:
            raise RuntimeError("AgentFrameworkExecutor is closed")

        async def _wrap() -> None:
            # The wired Python agents are synchronous; run them without blocking the loop.
            await asyncio.get_running_loop().run_in_executor(None, job)

        fut = asyncio.run_coroutine_threadsafe(_wrap(), self._loop)
        with self._lock:
            self._pending.add(fut)
        fut.add_done_callback(self._discard)

    def _discard(self, fut: Future) -> None:
        with self._lock:
            self._pending.discard(fut)

    def join(self) -> None:
        """Block until all submitted jobs have completed (drains for tests/shutdown)."""
        with self._lock:
            pending = list(self._pending)
        for fut in pending:
            try:
                fut.result()
            except Exception:  # noqa: BLE001 — a T2 failure must never surface on drain
                pass

    def close(self) -> None:
        """Stop the background loop (idempotent). Not part of the protocol; for clean teardown."""
        if self._closed:
            return
        self._closed = True
        self.join()
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5.0)


# --------------------------------------------------------------------------------------------
# Connected-Agent / tool adapter scaffolding (FH3 descriptors; FH4 binds them to a model).
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentSpec:
    """Declares one MAF Connected Agent by wrapping an existing AiraCare Python component.

    ``wraps`` is the dotted path of the class whose logic the agent exposes — no rewrite: FH4
    registers it as a MAF agent whose skills call straight through to that component.
    """

    name: str
    role: str
    instructions: str
    wraps: str


@dataclass(frozen=True)
class ToolSpec:
    """Declares one MAF tool/skill exposed to the Connected Agents."""

    name: str
    description: str
    wraps: str


def connected_agent_specs() -> list[AgentSpec]:
    """The six Connected Agents of the DELIBERATE tier, as MAF adapter descriptors.

    Ordering mirrors foundry-design.md §5. Each wraps an existing, tested Python class so the MAF
    graduation is orchestration-only — the reasoning logic is reused verbatim.
    """
    return [
        AgentSpec(
            name="risk-reasoning",
            role="Fuse the reported event with patient state into a considered risk level.",
            instructions=(
                "Given a scrubbed DailyLivingEvent and PatientState, produce the considered "
                "CloudAssessment. Never de-escalate below the edge level (safety floor)."
            ),
            wraps="airacare_foundry.assess.assessor.ConsideredAssessor",
        ),
        AgentSpec(
            name="knowledge",
            role="Ground caregiver advice in the care-guideline knowledge base (Azure AI Search).",
            instructions=(
                "Retrieve the top guideline snippets for the event/assessment and return advice "
                "grounded in the best match with citations, or nothing when irrelevant."
            ),
            wraps="airacare_foundry.agents.knowledge.KnowledgeAgent",
        ),
        AgentSpec(
            name="escalation",
            role="Drive the cloud-owned ack-tracked family -> community -> emergency ladder.",
            instructions=(
                "For an L3 considered assessment, start/advance the timed escalation ladder using "
                "the EscalationTimer tool; an ack resolves and cancels pending rungs."
            ),
            wraps="airacare_foundry.agents.escalation.EscalationAgent",
        ),
        AgentSpec(
            name="cognitive-trend",
            role="Model the voice-biomarker cognitive trajectory over filed events (compute).",
            instructions=(
                "Reduce each event's features to a scalar index and least-squares-fit over time; "
                "report slope/day and an improving|stable|declining direction. Compute, not tokens."
            ),
            wraps="airacare_foundry.agents.cognitive_trend.CognitiveTrendAgent",
        ),
        AgentSpec(
            name="briefing",
            role="Compose the family daily recap and the clinician monthly roll-up.",
            instructions=(
                "Summarize filed events into a reassuring family briefing and a clinical monthly "
                "roll-up (counts by type/level with the embedded cognitive trend)."
            ),
            wraps="airacare_foundry.agents.briefing.BriefingAgent",
        ),
        AgentSpec(
            name="policy-learning",
            role="Distill a versioned EdgePolicyUpdate from recurring patterns.",
            instructions=(
                "On recurring nighttime wanders, tune a personalized EdgePolicyUpdate (lower "
                "wander_confidence, tailored reassure_prompt, version++). Never touch the T1 reply."
            ),
            wraps="airacare_foundry.agents.policy_learning.PolicyLearningAgent",
        ),
    ]


def tool_specs() -> list[ToolSpec]:
    """The tools/skills the Connected Agents can call, as MAF adapter descriptors."""
    return [
        ToolSpec(
            name="notify",
            description="Send a caregiver/community notification (family, community, emergency).",
            wraps="airacare_foundry.tools.notify.NotificationTool",
        ),
        ToolSpec(
            name="geofence",
            description="Evaluate whether the patient has left a safe zone (wander support).",
            wraps="airacare_foundry.tools.notify.NotificationTool",
        ),
        ToolSpec(
            name="escalation-timer",
            description="Schedule/cancel timed escalation-ladder callbacks with ack windows.",
            wraps="airacare_foundry.tools.escalation_timer.Scheduler",
        ),
    ]


def build_workflow(model_endpoint: str | None = None, **_: object):
    """FH4 seam: assemble the Connected Agents + tools into a live MAF workflow.

    Left as a documented seam until a Foundry model deployment exists (FH4). It will use the SDK's
    ``WorkflowBuilder`` to register the :func:`connected_agent_specs` as MAF agents bound to
    ``model_endpoint`` and the :func:`tool_specs` as their skills, then hand the workflow to
    :class:`AgentFrameworkExecutor` to run per event.
    """
    _require_agent_framework()  # ensure the SDK is present before anyone wires a model
    raise NotImplementedError(
        "build_workflow is an FH4 seam: it binds the Connected Agents to a live Foundry model "
        "deployment. FH3 ships the offline executor + adapter descriptors only."
    )
