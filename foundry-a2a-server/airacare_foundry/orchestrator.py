"""Care Orchestrator — the cloud brain that turns a reported event into an assessment.

The edge is authoritative: it grades and acts on its own, then *reports* the event. The
orchestrator implements the same ``CloudGateway`` contract the edge expects
(``report`` + ``fetch_policy``) and composes the two decision tiers:

- **T1 — Considered assessment (synchronous):** :class:`AssessmentPolicy` loads patient
  state and returns a considered :class:`CloudAssessment` promptly. It is **off the edge's
  safety path** — the edge has already acted; this response is for records + caregiver comms.
- **T2 — Deliberate (asynchronous):** :class:`DeliberateTier` is scheduled fire-and-forget for
  deeper multi-agent reasoning, notifications, and escalation; it never blocks or changes
  the synchronous response.

Policy piggyback: :meth:`report` stamps the patient's current ``policy_version`` (from the
:class:`PolicyStore`) onto the assessment; when it exceeds the edge's version the edge lazily
calls :meth:`fetch_policy` to pull the new :class:`EdgePolicyUpdate`. Policy is *written* by
the deliberate tier's policy-learning agent, so a newly learned policy surfaces on the next
report. This mirrors ``LocalCloudStub``.
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
from airacare_foundry.agents.policy_learning import PolicyLearningAgent
from airacare_foundry.assess.assessor import ConsideredAssessor
from airacare_foundry.assess.policy import AssessmentPolicy
from airacare_foundry.config import FoundryConfig
from airacare_foundry.contracts import CloudAssessment, DailyLivingEvent, EdgePolicyUpdate
from airacare_foundry.store.base import (
    EventStore,
    PatientState,
    PatientStateStore,
    PolicyStore,
    policy_version_for,
)
from airacare_foundry.store.local import LocalEventStore, LocalPolicyStore, seeded_local_store


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

    Returns a ``(event, state, assessment) -> str`` callable only when the agents executor is
    selected AND a Foundry model endpoint + deployment resolve (plain or ``${ENV_VAR}``). The
    callable renders a scrubbed :func:`case_file` and runs the live MAF workflow to compose an
    advisory caregiver briefing. Any other configuration returns None — the deliberate tier then
    stays fully deterministic (local/CI default), preserving parity.
    """
    dc = config.deliberate
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

    Implements the edge's ``CloudGateway`` protocol: ``report`` (T1 assessment) and
    ``fetch_policy`` (lazy control-plane update served from the :class:`PolicyStore`).
    """

    def __init__(
        self,
        store: PatientStateStore,
        *,
        assessor: ConsideredAssessor | None = None,
        deliberate: DeliberateTier | None = None,
        policy: EdgePolicyUpdate | None = None,
        policy_version: int = 1,  # retained for compat; store-derived version takes precedence
        policy_store: PolicyStore | None = None,
        event_store: EventStore | None = None,
    ) -> None:
        self._store = store
        self._policy_store: PolicyStore = policy_store or LocalPolicyStore(":memory:")
        self._event_store: EventStore = event_store or LocalEventStore(":memory:")
        # Backward-compat: a policy passed directly seeds the store (e.g. tests/demo).
        if policy is not None:
            self._policy_store.upsert(policy)
        self._policy = AssessmentPolicy(store, assessor)
        self._deliberate = deliberate or DeliberateTier(enabled=False)
        self._trend = CognitiveTrendAgent(self._event_store)
        self._briefing = BriefingAgent(self._event_store, self._trend)

    def report(self, event: DailyLivingEvent) -> CloudAssessment | None:
        """T1 considered assessment; schedules deliberate reasoning fire-and-forget."""
        state = self._policy.resolve_state(event)
        version = policy_version_for(self._policy_store, event.patient_id)
        assessment = self._policy.assess(event, policy_version=version)
        # Enhancement tier — must never delay or alter the T1 response above.
        self._deliberate.schedule(event, state, assessment)
        return assessment

    def fetch_policy(self, patient_id: str, since_version: int) -> EdgePolicyUpdate | None:
        """Return the patient's stored policy when the edge is behind, else None."""
        policy = self._policy_store.get(patient_id)
        if policy is not None and policy.version > since_version:
            return policy
        return None

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
        store, policy_store, event_store = _build_stores(config)
        learning = PolicyLearningAgent(policy_store, enabled=config.deliberate.enabled)
        escalation = EscalationAgent(contacts=config.contacts, enabled=config.deliberate.enabled)
        kb: KnowledgeBase = (
            AzureSearchKnowledgeBase() if config.knowledge.backend == "azure"
            else LocalKnowledgeBase()
        )
        knowledge = KnowledgeAgent(kb, enabled=config.deliberate.enabled)
        deliberate = DeliberateTier(
            enabled=config.deliberate.enabled,
            policy_learning=learning,
            escalation=escalation,
            knowledge=knowledge,
            event_store=event_store,
            executor=_build_executor(config.deliberate.executor),
            narrator=_build_narrator(config),
        )
        return cls(store, deliberate=deliberate, policy_store=policy_store, event_store=event_store)


def _build_stores(
    config: FoundryConfig,
) -> tuple[PatientStateStore, PolicyStore, EventStore]:
    """Construct the (state, policy, event) store trio for the configured backend.

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
            CosmosPolicyStore,
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
        policy_store: PolicyStore = CosmosPolicyStore(
            endpoint, credential or "", **kwargs
        )
        event_store: EventStore = CosmosEventStore(
            endpoint, credential or "", **kwargs
        )
        return state_store, policy_store, event_store

    local_state = seeded_local_store(
        sc.sqlite_path,
        patient_id=config.patient.id,
        name=config.patient.name,
        disease_stage=config.patient.disease_stage,
    )
    return local_state, LocalPolicyStore(sc.sqlite_path), LocalEventStore(sc.sqlite_path)


def _default_store() -> PatientStateStore:
    """In-memory store seeded with the flagship patient — used when no config is supplied."""
    return seeded_local_store(":memory:")


def default_orchestrator() -> CareOrchestrator:
    """A ready-to-use orchestrator with sensible defaults (in-memory, flagship patient)."""
    return CareOrchestrator(_default_store())


__all__ = ["CareOrchestrator", "PatientState", "default_orchestrator"]
