"""Personalized T1 assessment: disease stage + baseline drift refine the considered level.

The considered level starts from the edge's authoritative level (a safety floor) and may be
escalated *upward* for higher-risk patients (design §6). It is never de-escalated, and the
default (moderate / no-state) path stays byte-identical to the edge stub (see
``test_report_parity``).
"""

from __future__ import annotations

import pytest

from airacare_foundry.assess.assessor import ConsideredAssessor
from airacare_foundry.contracts import DailyLivingEvent, utcnow
from airacare_foundry.orchestrator import CareOrchestrator
from airacare_foundry.store.base import PatientState
from airacare_foundry.store.local import seeded_local_store


def _wander_event(
    level: str, response: str, *, baseline_deviation: float = 0.95, patient_id: str = "p-001"
) -> DailyLivingEvent:
    return DailyLivingEvent(
        type="wander",
        confidence=0.9,
        timestamp=utcnow(),
        patient_id=patient_id,
        baseline_deviation=baseline_deviation,
        edge_assessed_level=level,  # type: ignore[arg-type]
        edge_action_taken="local_alert",
        context={"time_of_day": "night", "door_open": True, "response": response},
    )


def _state(stage: str, *, baseline_deviation: float = 0.0) -> PatientState:
    return PatientState(
        patient_id="p-001",
        disease_stage=stage,  # type: ignore[arg-type]
        baseline_deviation=baseline_deviation,
    )


def test_severe_stage_escalates_unclear_wander() -> None:
    # unclear -> edge L2; a severe-stage patient with high nighttime drift is refined to L3.
    event = _wander_event("L2", "unclear")
    result = ConsideredAssessor().assess(event, _state("severe"))

    assert result.considered_level == "L3"
    assert "refined from L2" in result.reason
    # Comms track the refined level: L3 adds the community rung.
    channels = [n.channel for n in result.caregiver_notifications]
    assert channels == ["family", "community"]


def test_severe_stage_does_not_escalate_reassured_patient() -> None:
    # response=ok means the patient explicitly reassured -> not escalated even for severe.
    event = _wander_event("L1", "ok")
    result = ConsideredAssessor().assess(event, _state("severe"))

    assert result.considered_level == "L1"
    assert "refined" not in result.reason
    assert result.caregiver_notifications == []


def test_moderate_stage_preserves_edge_level() -> None:
    event = _wander_event("L2", "unclear")
    # moderate weight is 1.0 -> no refinement -> parity with the edge stub.
    no_state = ConsideredAssessor().assess(event)
    moderate = ConsideredAssessor().assess(event, _state("moderate"))

    assert moderate.considered_level == "L2"
    assert moderate.model_dump_json() == no_state.model_dump_json()


def test_mild_stage_never_de_escalates() -> None:
    event = _wander_event("L2", "unclear")
    result = ConsideredAssessor().assess(event, _state("mild"))
    # The edge level is a safety floor: mild weighting must not drop below it.
    assert result.considered_level == "L2"


def test_severe_stage_low_drift_stays_put() -> None:
    # High-risk gate needs real baseline drift; a low-drift event is not escalated.
    event = _wander_event("L2", "unclear", baseline_deviation=0.4)
    result = ConsideredAssessor().assess(event, _state("severe", baseline_deviation=0.4))
    assert result.considered_level == "L2"


def test_severe_fuses_persisted_baseline_drift() -> None:
    # Event drift alone is low, but the patient's persisted rolling baseline is high ->
    # the fused drift clears the bar and escalates.
    event = _wander_event("L2", "unclear", baseline_deviation=0.3)
    result = ConsideredAssessor().assess(event, _state("severe", baseline_deviation=0.95))
    assert result.considered_level == "L3"


def test_orchestrator_uses_seeded_severe_state() -> None:
    store = seeded_local_store(":memory:", disease_stage="severe")
    orch = CareOrchestrator(store)
    # unclear -> edge L2 -> refined to L3 for the severe seeded patient.
    result = orch.report(_wander_event("L2", "unclear"))
    assert result.considered_level == "L3"


@pytest.mark.parametrize("level,response", [("L3", "no_response"), ("L0", None)])
def test_extreme_levels_are_stable(level: str, response: str | None) -> None:
    # L3 is already the ceiling; L0 is not actionable -> neither moves.
    event = _wander_event(level, response or "unclear", baseline_deviation=0.95)
    if response is None:
        event.context["response"] = None
    result = ConsideredAssessor().assess(event, _state("severe"))
    assert result.considered_level == level
