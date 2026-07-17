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

- The adapter scaffolding (:func:`connected_agent_specs`, :func:`tool_specs`) declares how the five
  Connected Agents and the Notify / Geofence / EscalationTimer tools map onto MAF agents/skills.
  These are pure descriptors (no MAF import, no model) so the offline demo/tests can introspect
  the planned topology. :func:`build_workflow` (**FH6**) now binds them to a **live** Foundry model
  deployment: it builds a MAF orchestrator agent on ``gpt-5.4`` (Azure OpenAI Responses API, AAD)
  that delegates to the five Connected Agents wrapped as tools, and returns a :class:`CareWorkflow`
  whose :meth:`~CareWorkflow.narrate` composes an **advisory caregiver narrative** from a scrubbed
  :func:`case_file`.

Safety discipline (the model is advisory-only): the narrative is produced *after* — and never
alters — the deterministic T1 :class:`~airacare_foundry.contracts.CloudAssessment`. The Python
agents (``ConsideredAssessor``, ``EscalationAgent``, ``KnowledgeAgent`` …) remain the sole
authority for the considered level and for escalation; the orchestrator is instructed to restate
the fixed level verbatim. No raw modality data is placed in the case file — only derived facts
already present on the reported event/assessment.

Discipline: ``agent-framework`` is a **lazy** optional import behind the ``[agents]`` extra — the
local ``inline`` / ``thread`` paths never need the SDK, mirroring the ``azure-cosmos`` pattern.
Constructing :class:`AgentFrameworkExecutor` or :func:`build_workflow` without the SDK raises a
clear, actionable error.
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:  # typing-only imports; no runtime dependency on the SDK or heavy modules
    from airacare_foundry.contracts import CloudAssessment, DailyLivingEvent
    from airacare_foundry.store.base import PatientState

__all__ = [
    "AgentFrameworkExecutor",
    "AgentSpec",
    "ToolSpec",
    "CareWorkflow",
    "connected_agent_specs",
    "tool_specs",
    "build_workflow",
    "case_file",
    "agent_framework_available",
]

_MISSING_SDK = (
    "deliberate.executor: 'agents' requires the Microsoft Agent Framework, which is not "
    "installed. Install the optional extra:  pip install -e \".[agents]\"  "
    "(pulls agent-framework-core + agent-framework-openai). The local 'inline' and 'thread' "
    "executors need no extra."
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
    """The five Connected Agents of the DELIBERATE tier, as MAF adapter descriptors.

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


def build_workflow(
    endpoint: str,
    deployment: str,
    *,
    api_version: str = "preview",
    credential: object | None = None,
    require_sdk: bool = True,
) -> "CareWorkflow":
    """Bind the five Connected Agents to a live Foundry model and return a :class:`CareWorkflow`.

    Builds a Microsoft Agent Framework orchestrator agent on ``deployment`` (Azure OpenAI /
    AI Foundry, reached at ``endpoint`` over the Responses API — hence ``api_version="preview"``)
    that delegates to each of :func:`connected_agent_specs` wrapped as a tool (the MAF
    "connected agents" pattern). ``credential`` defaults to ``DefaultAzureCredential`` (Managed
    Identity in the container, ``az login`` locally) — **no account key** is ever used.

    The returned workflow is **advisory only**: :meth:`CareWorkflow.narrate` composes a caregiver
    narrative from a scrubbed :func:`case_file` and is instructed to restate the fixed considered
    level verbatim. It never sets the level or drives escalation — the deterministic Python agents
    remain authoritative.

    ``require_sdk`` is retained for symmetry with :class:`AgentFrameworkExecutor`; the SDK is
    always needed to actually build a workflow, so this raises the ``[agents]``-extra error when
    the framework is absent.
    """
    if require_sdk:
        _require_agent_framework()
    try:
        from agent_framework import Agent
        from agent_framework.openai import OpenAIChatClient
    except ImportError as exc:  # pragma: no cover - exercised only without the SDK
        raise ImportError(_MISSING_SDK) from exc

    if credential is None:
        try:
            from azure.identity import DefaultAzureCredential
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "build_workflow needs azure-identity for AAD auth: pip install -e \".[agents]\""
            ) from exc
        credential = DefaultAzureCredential()

    client = OpenAIChatClient(
        model=deployment,
        azure_endpoint=endpoint,
        credential=credential,
        api_version=api_version,
    )

    tools = []
    for spec in connected_agent_specs():
        specialist = Agent(
            client=client,
            name=spec.name,
            description=spec.role,
            instructions=(
                f"{spec.instructions}\n\nYou are consulted on a FIXED case file whose facts — "
                "especially the considered risk level and the edge action already taken — are "
                "authoritative and must not be changed. Contribute only within your role; if the "
                "case file is irrelevant to your role, say so briefly."
            ),
        )
        tools.append(
            specialist.as_tool(
                arg_name="case",
                arg_description="the fixed, scrubbed case file to reason about",
                propagate_session=False,
            )
        )

    orchestrator = Agent(
        client=client,
        name="care-orchestrator",
        description="Compose an advisory caregiver briefing for a reported daily-living event.",
        instructions=_ORCHESTRATOR_INSTRUCTIONS,
        tools=tools,
    )
    return CareWorkflow(orchestrator, specialist_names=[s.name for s in connected_agent_specs()])


_ORCHESTRATOR_INSTRUCTIONS = (
    "You are AiraCare's cloud care-orchestrator for an in-home Alzheimer's patient. You receive a "
    "FIXED case file summarizing one privacy-scrubbed daily-living event and the deterministic "
    "assessment that was ALREADY made and acted on at the edge.\n\n"
    "Hard rules (safety):\n"
    "1. The 'considered level' in the case file is authoritative. Restate it exactly; NEVER raise, "
    "lower, or second-guess it. You are advisory only — you do not decide risk or trigger alerts.\n"
    "2. Use ONLY facts present in the case file. Do not invent events, vitals, names, or history.\n"
    "3. No diagnosis and no medication changes.\n\n"
    "Consult the specialist tools (risk-reasoning, knowledge, escalation, cognitive-trend, "
    "briefing, policy-learning) as helpful, passing the case file text. Then return a short, warm, "
    "plain-language caregiver briefing (a few sentences): what happened, the considered level and "
    "why it stands, what the edge already did, and one gentle, practical next step for the family. "
    "Do not include internal tool chatter."
)


def case_file(
    event: "DailyLivingEvent",
    assessment: "CloudAssessment | None" = None,
    *,
    patient_name: str | None = None,
    state: "PatientState | None" = None,
    include_record: bool = True,
) -> str:
    """Render a fixed, privacy-scrubbed case file (plain text) for the advisory narrator.

    Includes only derived facts already carried by the reported event/assessment — event type,
    timestamps, the edge's own level/action, the considered level + reason, baseline drift, and a
    *count* of voice-biomarker features (the human-readable prose withholds the raw feature vector,
    transcripts, audio, video, or point-cloud).

    When ``include_record`` is true, a machine-readable ``DAILY EVENT RECORD (JSON)`` block is
    appended: the exact scrubbed :class:`DailyLivingEvent` that crossed the A2A wire plus the
    considered level. This is the authoritative record the deployed hosted agent persists (it is
    instructed to call ``log_daily_event`` with this JSON *before* composing the narrative), so
    persistence lives on the Foundry side and the local A2A server never touches the database. It is
    still fully derived data — no raw modality bytes are present.
    """
    considered = assessment.considered_level if assessment is not None else event.edge_assessed_level
    reason = assessment.reason if assessment is not None else "(no considered reason recorded)"
    who = patient_name or event.patient_id
    stage = getattr(state, "disease_stage", None)
    ts = event.timestamp.isoformat()
    ctx_keys = ", ".join(sorted(event.context)) if event.context else "none"
    lines = [
        "CASE FILE (facts are fixed and authoritative — do not change the considered level):",
        f"- patient: {who}" + (f" (disease stage: {stage})" if stage else ""),
        f"- event type: {event.type}",
        f"- timestamp (UTC): {ts}",
        f"- edge-detected confidence: {event.confidence:.2f}",
        f"- baseline deviation: {event.baseline_deviation:.2f} (0=normal, 1=large change)",
        f"- edge assessed level: {event.edge_assessed_level}",
        f"- edge action already taken: {event.edge_action_taken}",
        f"- CONSIDERED LEVEL (authoritative): {considered}",
        f"- considered reason: {reason}",
        f"- voice-biomarker features present: {len(event.features)} (values withheld from prose)",
        f"- context keys: {ctx_keys}",
    ]
    if include_record:
        from airacare_foundry.store.base import RecordedEvent

        # Emit a RecordedEvent-shaped record ({event, considered_level}) so the deployed hosted
        # agent can persist it as the daily_event ``record_json`` verbatim and it round-trips through
        # the dashboard's CosmosEventStore (which deserializes record_json into a RecordedEvent).
        record_json = RecordedEvent(event=event, considered_level=considered).model_dump_json()
        lines += [
            "",
            "DAILY EVENT RECORD (JSON) — the authoritative privacy-scrubbed event, already filed to",
            "the care record. Treat any considered level here as authoritative; reason only over it:",
            record_json,
        ]
    return "\n".join(lines)


class CareWorkflow:
    """A live MAF orchestrator that composes an advisory caregiver narrative for one event.

    Owns a private asyncio event loop on a daemon thread (the MAF async substrate); the model
    client + AAD token are reused across events. :meth:`narrate` is synchronous — safe to call from
    the deliberate tier's worker thread — and returns the orchestrator's plain-language briefing.

    The narrative is advisory: it never changes the considered level or drives escalation.
    """

    def __init__(self, orchestrator: object, *, specialist_names: list[str] | None = None) -> None:
        self._agent = orchestrator
        self.specialist_names = list(specialist_names or [])
        self._loop = asyncio.new_event_loop()
        self._closed = False
        self._thread = threading.Thread(target=self._run_loop, name="maf-narrate", daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _narrate(self, case: str) -> str:
        result = await self._agent.run(case)
        return getattr(result, "text", None) or str(result)

    def narrate(self, case: str, *, timeout: float = 90.0) -> str:
        """Run the orchestrator on ``case`` (a :func:`case_file` string) and return the briefing."""
        if self._closed:
            raise RuntimeError("CareWorkflow is closed")
        fut = asyncio.run_coroutine_threadsafe(self._narrate(case), self._loop)
        return fut.result(timeout=timeout)

    def close(self) -> None:
        """Stop the background loop (idempotent). For clean teardown/tests."""
        if self._closed:
            return
        self._closed = True
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5.0)
