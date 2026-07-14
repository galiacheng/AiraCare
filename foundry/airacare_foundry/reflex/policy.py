"""Reflex policy — loads patient state and applies the reflex assessor.

The policy is the synchronous entry point the orchestrator calls. It reads the
:class:`PatientStateStore` for the event's patient (disease stage + rolling baseline) and
hands that state to the :class:`ReflexGrader`. A store miss falls back to a safe default
(moderate stage) so assessment never fails on an unknown patient.

Loading state here (not in the grader) keeps the grader pure and the store swappable.
"""

from __future__ import annotations

from airacare_foundry.contracts import CloudAssessment, DailyLivingEvent
from airacare_foundry.reflex.grader import ReflexGrader
from airacare_foundry.store.base import PatientState, PatientStateStore


class ReflexPolicy:
    def __init__(self, store: PatientStateStore, grader: ReflexGrader | None = None) -> None:
        self._store = store
        self._grader = grader or ReflexGrader()

    def resolve_state(self, event: DailyLivingEvent) -> PatientState:
        """Return stored state for the event's patient, or a safe default on a miss."""
        state = self._store.get(event.patient_id)
        if state is not None:
            return state
        return PatientState(patient_id=event.patient_id)  # safe default: moderate stage

    def assess(
        self, event: DailyLivingEvent, *, policy_version: int = 1
    ) -> CloudAssessment:
        state = self.resolve_state(event)
        return self._grader.assess(event, state, policy_version=policy_version)
