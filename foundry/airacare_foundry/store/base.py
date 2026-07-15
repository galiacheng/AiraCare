"""Store contracts — patient state (read by T1) and edge policy (control-plane feedback).

Decision #6 = C: this scaffold uses **local** stores (see ``local.py``). The
:class:`PatientStateStore` and :class:`PolicyStore` protocols keep the assessment policy and
the policy-learning seam decoupled from the backend so a Cosmos DB / Fabric implementation
(``cosmos.py``) can drop in later behind the same interfaces with no caller changes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from airacare_foundry.contracts import DailyLivingEvent, EdgePolicyUpdate, Grade, utcnow

DiseaseStage = Literal["mild", "moderate", "severe"]

# The edge boots at policy version 1 (its own config baseline). A patient with no learned
# policy therefore piggybacks version 1, so the edge is already current and never fetches.
BASE_POLICY_VERSION = 1


class PatientState(BaseModel):
    """Persisted per-patient state that personalizes cloud grading.

    ``baseline_deviation`` is the patient's own rolling-baseline drift the cloud can fuse
    with the incoming event; the disease stage weights how aggressively to escalate.
    """

    patient_id: str
    name: str = ""
    disease_stage: DiseaseStage = "moderate"
    baseline_deviation: float = Field(default=0.0, ge=0.0, le=1.0)


@runtime_checkable
class PatientStateStore(Protocol):
    """Read/write access to per-patient state, keyed by ``patient_id``."""

    def get(self, patient_id: str) -> PatientState | None:
        """Return the stored state for a patient, or ``None`` if unknown."""
        ...

    def upsert(self, state: PatientState) -> None:
        """Insert or replace the state for ``state.patient_id``."""
        ...


@runtime_checkable
class PolicyStore(Protocol):
    """Versioned per-patient :class:`EdgePolicyUpdate` — the control-plane feedback channel.

    The cloud's learning is distilled into a policy and stored here; the orchestrator
    piggybacks its ``version`` onto every :class:`CloudAssessment` and serves the full policy
    via ``fetch_policy`` when the edge is behind. Only the latest policy per patient is kept
    (MVP); a production backend may retain history.
    """

    def get(self, patient_id: str) -> EdgePolicyUpdate | None:
        """Return the latest stored policy for a patient, or ``None`` if none learned yet."""
        ...

    def upsert(self, policy: EdgePolicyUpdate) -> None:
        """Insert or replace the latest policy for ``policy.patient_id``."""
        ...


def policy_version_for(store: PolicyStore, patient_id: str) -> int:
    """The version to piggyback for a patient: the learned policy's, or the base version."""
    policy = store.get(patient_id)
    return policy.version if policy is not None else BASE_POLICY_VERSION


class RecordedEvent(BaseModel):
    """A filed :class:`DailyLivingEvent` plus the cloud's considered level — the operational
    record the batch agents (Cognitive-Trend, Briefing) and Power BI analytics read.

    Only privacy-scrubbed :class:`DailyLivingEvent` data is stored (never raw audio/video);
    this mirrors what the production Cosmos DB → Fabric/OneLake store would hold.
    """

    event: DailyLivingEvent
    considered_level: Grade
    recorded_at: datetime = Field(default_factory=utcnow)


@runtime_checkable
class EventStore(Protocol):
    """Append-only log of filed events per patient — the analytics/briefing source of truth."""

    def append(self, record: RecordedEvent) -> None:
        """File one recorded event."""
        ...

    def list_for_patient(
        self,
        patient_id: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[RecordedEvent]:
        """Return the patient's filed events ordered by event timestamp (ascending).

        ``since`` is inclusive, ``until`` is exclusive; both filter on the event's own
        ``timestamp`` (not ``recorded_at``) so trend/briefing windows are wall-clock aligned.
        """
        ...
