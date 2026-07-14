"""Patient-state store — the contract the reflex policy reads from.

Decision #6 = C: this scaffold uses a **local** store (see ``local.py``). The
:class:`PatientStateStore` protocol keeps the reflex policy decoupled from the backend so
a Cosmos DB / Fabric implementation (``cosmos.py``) can drop in later behind the same
interface with no policy changes.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

DiseaseStage = Literal["mild", "moderate", "severe"]


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
