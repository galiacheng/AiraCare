"""Care Orchestrator — the cloud brain that turns a reported event into an assessment.

The edge is authoritative: it grades and acts on its own, then *reports* the event. The
orchestrator implements the ``report`` half of the ``CloudGateway`` contract the edge expects
and composes the two decision tiers:

- **T1 — Considered assessment (synchronous):** :class:`AssessmentPolicy` loads patient
  state and returns a considered :class:`CloudAssessment` promptly. It is **off the edge's
  safety path** — the edge has already acted; this response is for records + caregiver comms.
- **T2 — Deliberate (asynchronous):** :class:`DeliberateTier` is scheduled fire-and-forget for
  deeper multi-agent reasoning, notifications, and escalation; it never blocks or changes
  the synchronous response.

The server carries **no edge-policy control plane**: the edge already knows how to grade and
escalate on its own, so the orchestrator neither learns nor serves policy. Every assessment
piggybacks a constant ``policy_version`` (:data:`BASE_POLICY_VERSION`) equal to the edge's own
baseline, so the edge is always current and never calls ``fetch_policy``. The
``CloudAssessment.policy_version`` field is retained purely for wire-compatibility with the
frozen edge contract.
"""

from __future__ import annotations

from datetime import date

from airacare_foundry.agents.briefing import Briefing, BriefingAgent
from airacare_foundry.agents.cognitive_trend import CognitiveTrend, CognitiveTrendAgent
from airacare_foundry.agents.deliberate import DeliberateTier
from airacare_foundry.agents.escalation import EscalationAgent
from airacare_foundry.agents.knowledge import (
    AzureSearchKnowledgeBase,
    KnowledgeAgent,
    KnowledgeBase,
    LocalKnowledgeBase,
)
from airacare_foundry.assess.assessor import ConsideredAssessor
from airacare_foundry.assess.policy import AssessmentPolicy
from airacare_foundry.config import FoundryConfig
from airacare_foundry.contracts import CloudAssessment, DailyLivingEvent
from airacare_foundry.store.base import (
    EventStore,
    PatientState,
    PatientStateStore,
)
from airacare_foundry.store.local import LocalEventStore, seeded_local_store


def _build_executor(kind: str):
    """Construct the DeliberateExecutor for the configured ``deliberate.executor`` mode.

    ``inline`` (default) runs T2 in-thread — deterministic for tests/demo/CI. ``thread`` runs it
    on a background worker so ``report`` returns immediately (the hosted-server default).
    ``agents`` runs on the Microsoft Agent Framework runtime (FH3) behind the ``[agents]`` extra;
    the SDK is imported lazily, so selecting it without the extra raises a clear install error.
    """
    from airacare_foundry.agents.deliberate import InlineExecutor, ThreadExecutor

    if kind == "thread":
        return ThreadExecutor()
    if kind == "agents":
        from airacare_foundry.agents.agent_framework import AgentFrameworkExecutor

        return AgentFrameworkExecutor()
    return InlineExecutor()


def _build_narrator(config: FoundryConfig):
    """Build the advisory model narrator for ``executor: agents`` (or None to stay deterministic).

    Two model-backed narrators are supported; both are advisory-only (they render a scrubbed
    :func:`case_file` and return a caregiver briefing, never changing the considered level):

    1. **Deployed Foundry Hosted Agent** (``hosted_agent_endpoint`` set) — delegates the briefing to
       a separately deployed agent over the OpenAI Responses protocol (grounded in Foundry IQ). This
       takes **precedence** and works with the async executors (``agents``/``thread``).
    2. **In-process MAF workflow** (``foundry_endpoint`` + ``foundry_deployment`` set, ``executor:
       agents``) — binds the five Connected Agents to a shared model here in the process.

    Any other configuration returns None — the deliberate tier then stays fully deterministic
    (local/CI default), preserving parity.
    """
    dc = config.deliberate

    # (1) Deployed Foundry Hosted Agent (Responses protocol) — takes precedence when configured.
    #     It's a plain HTTPS + AAD call, so it runs on either async executor (no MAF extra needed).
    hosted_endpoint = dc.resolve_hosted_agent_endpoint()
    if hosted_endpoint and dc.executor in ("agents", "thread"):
        from airacare_foundry.agents.agent_framework import case_file
        from airacare_foundry.agents.hosted_agent import HostedAgentNarrator

        agent = HostedAgentNarrator(
            hosted_endpoint,
            dc.resolve_hosted_agent_name(),
            token_scope=dc.hosted_agent_token_scope,
        )

        def narrate_hosted(event: DailyLivingEvent, state, assessment: CloudAssessment | None) -> str:
            return agent.narrate(
                case_file(event, assessment, patient_name=config.patient.name, state=state)
            )

        return narrate_hosted

    # (2) In-process MAF workflow bound to a shared Foundry model — requires the agents executor.
    if dc.executor != "agents":
        return None
    endpoint = dc.resolve_foundry_endpoint()
    deployment = dc.resolve_foundry_deployment()
    if not endpoint or not deployment:
        return None

    from airacare_foundry.agents.agent_framework import build_workflow, case_file

    workflow = build_workflow(endpoint, deployment, api_version=dc.foundry_api_version)

    def narrate(event: DailyLivingEvent, state, assessment: CloudAssessment | None) -> str:
        return workflow.narrate(
            case_file(event, assessment, patient_name=config.patient.name, state=state)
        )

    return narrate


class CareOrchestrator:
    """Considered-assessment-first cloud gateway with an asynchronous deliberate tier.

    Implements the ``report`` half of the edge's ``CloudGateway`` protocol (T1 assessment).
    The server holds no edge-policy control plane; every assessment carries a constant
    ``policy_version`` so the edge is always current and never calls ``fetch_policy``.
    """

    def __init__(
        self,
        store: PatientStateStore,
        *,
        assessor: ConsideredAssessor | None = None,
        deliberate: DeliberateTier | None = None,
        event_store: EventStore | None = None,
    ) -> None:
        self._store = store
        self._event_store: EventStore = event_store or LocalEventStore(":memory:")
        self._policy = AssessmentPolicy(store, assessor)
        self._deliberate = deliberate or DeliberateTier(enabled=False)
        self._trend = CognitiveTrendAgent(self._event_store)
        self._briefing = BriefingAgent(self._event_store, self._trend)

    def report(self, event: DailyLivingEvent) -> CloudAssessment | None:
        """T1 considered assessment; schedules deliberate reasoning fire-and-forget."""
        state = self._policy.resolve_state(event)
        assessment = self._policy.assess(event)
        # Enhancement tier — must never delay or alter the T1 response above.
        self._deliberate.schedule(event, state, assessment)
        return assessment

    def drain(self) -> None:
        """Await any in-flight deliberate (T2) jobs — used by the server for graceful shutdown."""
        self._deliberate.join()

    # -- Batch analytics (T2) — read the filed EventStore; never on the safety path. --------

    def cognitive_trend(self, patient_id: str) -> CognitiveTrend:
        """The patient's voice-biomarker cognitive trajectory over all filed events."""
        return self._trend.analyze(patient_id)

    def family_briefing(self, patient_id: str, day: date | None = None) -> Briefing:
        """A plain-language family daily briefing (defaults to today, UTC)."""
        return self._briefing.family_daily(patient_id, day)

    def clinician_briefing(self, patient_id: str, year: int, month: int) -> Briefing:
        """A clinician monthly roll-up including the cognitive trajectory."""
        return self._briefing.clinician_monthly(patient_id, year, month)

    @classmethod
    def from_config(cls, config: FoundryConfig) -> "CareOrchestrator":
        """Build an orchestrator from config, selecting the local or Cosmos store backend."""
        store, event_store = _build_stores(config)
        escalation = EscalationAgent(contacts=config.contacts, enabled=config.deliberate.enabled)
        kb: KnowledgeBase = (
            AzureSearchKnowledgeBase() if config.knowledge.backend == "azure"
            else LocalKnowledgeBase()
        )
        knowledge = KnowledgeAgent(kb, enabled=config.deliberate.enabled)
        deliberate = DeliberateTier(
            enabled=config.deliberate.enabled,
            escalation=escalation,
            knowledge=knowledge,
            event_store=event_store,
            executor=_build_executor(config.deliberate.executor),
            narrator=_build_narrator(config),
        )
        return cls(store, deliberate=deliberate, event_store=event_store)


def _build_stores(
    config: FoundryConfig,
) -> tuple[PatientStateStore, EventStore]:
    """Construct the (state, event) store pair for the configured backend.

    ``local`` uses the seeded SQLite stores (demo/MVP). ``cosmos`` builds the production
    Azure Cosmos DB stores (partition = ``/patient_id``); it requires ``cosmos_endpoint`` /
    ``cosmos_credential`` and the ``[cosmos]`` extra. The flagship patient is **not** auto-seeded
    into Cosmos — production state is provisioned out of band — but is upserted if absent so the
    demo patient works against a fresh account.
    """
    sc = config.store
    if sc.backend == "cosmos":
        credential = sc.resolve_credential()
        endpoint = sc.resolve_endpoint()
        database = sc.resolve_database()
        if not endpoint or (sc.cosmos_auth == "key" and not credential):
            raise ValueError(
                "store.backend: cosmos requires store.cosmos_endpoint and store.cosmos_credential."
            )
        from airacare_foundry.store.cosmos import (
            CosmosEventStore,
            CosmosPatientStateStore,
        )

        kwargs = {
            "database": database,
            "auth": sc.cosmos_auth,
            "tls_verify": sc.cosmos_tls_verify,
        }
        state_store: PatientStateStore = CosmosPatientStateStore(
            endpoint, credential or "", **kwargs
        )
        if state_store.get(config.patient.id) is None:
            state_store.upsert(
                PatientState(
                    patient_id=config.patient.id,
                    name=config.patient.name,
                    disease_stage=config.patient.disease_stage,
                )
            )
        event_store: EventStore = CosmosEventStore(
            endpoint, credential or "", **kwargs
        )
        return state_store, event_store

    local_state = seeded_local_store(
        sc.sqlite_path,
        patient_id=config.patient.id,
        name=config.patient.name,
        disease_stage=config.patient.disease_stage,
    )
    return local_state, LocalEventStore(sc.sqlite_path)


def _default_store() -> PatientStateStore:
    """In-memory store seeded with the flagship patient — used when no config is supplied."""
    return seeded_local_store(":memory:")


def default_orchestrator() -> CareOrchestrator:
    """A ready-to-use orchestrator with sensible defaults (in-memory, flagship patient)."""
    return CareOrchestrator(_default_store())


__all__ = ["CareOrchestrator", "PatientState", "default_orchestrator"]
