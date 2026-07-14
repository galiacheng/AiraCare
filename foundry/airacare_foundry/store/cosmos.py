"""Cosmos DB / Fabric patient-state store — PLACEHOLDER (not wired in this scaffold).

Decision #6 = C: this scaffold deliberately uses the local SQLite store (``local.py``). This
module exists only to reserve the seam: it implements the same :class:`PatientStateStore`
protocol so a real Azure Cosmos DB (or Microsoft Fabric) backend can drop in later without
touching the reflex policy or orchestrator. Every method raises ``NotImplementedError``.
"""

from __future__ import annotations

from airacare_foundry.store.base import PatientState

_NOT_WIRED = (
    "CosmosPatientStateStore is a placeholder in this scaffold (Decision #6 = C: local "
    "store). Use LocalPatientStateStore. Cosmos DB / Fabric wiring is future work; install "
    "the [cosmos] extra and implement this class when ready."
)


class CosmosPatientStateStore:
    """Placeholder implementation of :class:`PatientStateStore` for a future Cosmos backend."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError(_NOT_WIRED)

    def get(self, patient_id: str) -> PatientState | None:
        raise NotImplementedError(_NOT_WIRED)

    def upsert(self, state: PatientState) -> None:
        raise NotImplementedError(_NOT_WIRED)
