"""Store contracts — patient state (read by T1) and the filed-event log (read by analytics).

Decision #6 = C: this scaffold uses **local** stores (see ``local.py``). The
:class:`PatientStateStore` and :class:`EventStore` protocols keep the assessment tier and the
batch trend/briefing agents decoupled from the backend so a Cosmos DB / Fabric implementation
(``cosmos.py``) can drop in later behind the same interfaces with no caller changes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from airacare_foundry.contracts import DailyLivingEvent, Grade, utcnow

DiseaseStage = Literal["mild", "moderate", "severe"]

# The edge boots at policy version 1 (its own config baseline). The server no longer learns or
# serves edge policy; it simply piggybacks this constant version on every assessment so the edge
# is already current and never calls ``fetch_policy``. The frozen A2A contract keeps the
# ``policy_version`` field for wire-compatibility with the edge.
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
