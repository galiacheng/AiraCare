"""Care Orchestrator — the cloud brain that turns a reported event into an assessment.

The edge is authoritative: it grades and acts on its own, then *reports* the event. The
orchestrator implements the same ``CloudGateway`` contract the edge expects
(``report`` + ``fetch_policy``) and composes the two decision tiers:

- **REFLEX (synchronous):** :class:`ReflexPolicy` loads patient state and returns a safe,
  considered :class:`CloudAssessment` inside the edge's 5s budget.
- **DELIBERATE (asynchronous):** :class:`DeliberateTier` is scheduled fire-and-forget for
  deeper multi-agent reasoning, notifications, and escalation; it never blocks or changes
  the synchronous response.

Policy piggyback: :meth:`report` stamps the current ``policy_version`` onto the assessment;
when it exceeds the edge's version the edge lazily calls :meth:`fetch_policy` to pull a new
:class:`EdgePolicyUpdate`. This mirrors ``LocalCloudStub``.
"""

from __future__ import annotations

from airacare_foundry.agents.deliberate import DeliberateTier
from airacare_foundry.config import FoundryConfig
from airacare_foundry.contracts import CloudAssessment, DailyLivingEvent, EdgePolicyUpdate
from airacare_foundry.reflex.grader import ReflexGrader
from airacare_foundry.reflex.policy import ReflexPolicy
from airacare_foundry.store.base import PatientState, PatientStateStore
from airacare_foundry.store.local import seeded_local_store


class CareOrchestrator:
    """Reflex-first cloud gateway with an asynchronous deliberate tier.

    Implements the edge's ``CloudGateway`` protocol: ``report`` (sync assessment) and
    ``fetch_policy`` (lazy control-plane update).
    """

    def __init__(
        self,
        store: PatientStateStore,
        *,
        grader: ReflexGrader | None = None,
        deliberate: DeliberateTier | None = None,
        policy: EdgePolicyUpdate | None = None,
        policy_version: int = 1,
    ) -> None:
        self._store = store
        self._policy_obj = policy
        self._policy_version = policy.version if policy is not None else policy_version
        self._policy = ReflexPolicy(store, grader)
        self._deliberate = deliberate or DeliberateTier(enabled=False)

    def report(self, event: DailyLivingEvent) -> CloudAssessment | None:
        """Synchronous reflex assessment; schedules deliberate reasoning fire-and-forget."""
        state = self._policy.resolve_state(event)
        assessment = self._policy.assess(event, policy_version=self._policy_version)
        # Enhancement tier — must never delay or alter the reflex response.
        self._deliberate.schedule(event, state)
        return assessment

    def fetch_policy(self, patient_id: str, since_version: int) -> EdgePolicyUpdate | None:
        """Return a newer policy for the patient, or None when nothing changed."""
        if self._policy_obj is not None and self._policy_obj.version > since_version:
            return self._policy_obj
        return None

    @classmethod
    def from_config(cls, config: FoundryConfig) -> "CareOrchestrator":
        """Build an orchestrator from config: local store seeded with the default patient."""
        if config.store.backend == "cosmos":
            raise NotImplementedError(
                "Cosmos backend is a placeholder in this scaffold (Decision #6 = C). "
                "Set store.backend: local."
            )
        store = seeded_local_store(
            config.store.sqlite_path,
            patient_id=config.patient.id,
            name=config.patient.name,
            disease_stage=config.patient.disease_stage,
        )
        return cls(store, deliberate=DeliberateTier(enabled=config.deliberate.enabled))


def _default_store() -> PatientStateStore:
    """In-memory store seeded with the flagship patient — used when no config is supplied."""
    return seeded_local_store(":memory:")


def default_orchestrator() -> CareOrchestrator:
    """A ready-to-use orchestrator with sensible defaults (in-memory, flagship patient)."""
    return CareOrchestrator(_default_store())


__all__ = ["CareOrchestrator", "PatientState", "default_orchestrator"]
