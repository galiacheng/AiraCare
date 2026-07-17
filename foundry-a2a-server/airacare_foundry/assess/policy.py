"""Assessment policy — loads patient state and applies the considered assessor.

The policy is the T1 entry point the orchestrator calls. It reads the
:class:`PatientStateStore` for the event's patient (disease stage + rolling baseline) and
hands that state to the :class:`ConsideredAssessor`. A store miss falls back to a safe
default (moderate stage) so assessment never fails on an unknown patient.

Loading state here (not in the assessor) keeps the assessor pure and the store swappable.
"""

from __future__ import annotations

from airacare_foundry.assess.assessor import ConsideredAssessor
from airacare_foundry.contracts import CloudAssessment, DailyLivingEvent
from airacare_foundry.store.base import PatientState, PatientStateStore


class AssessmentPolicy:
    def __init__(self, store: PatientStateStore, assessor: ConsideredAssessor | None = None) -> None:
        self._store = store
        self._assessor = assessor or ConsideredAssessor()

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
        return self._assessor.assess(event, state, policy_version=policy_version)
