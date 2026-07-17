"""Deterministic considered assessment: parity with the edge stub + patient-state personalization.

In the standard-A2A topology the hosted agent owns the considered level (the standalone
foundry-a2a-server is retired), so these tests pin the two invariants that keep it safe:

- **Parity** — for the flagship ``wander`` cases the ported :class:`ConsideredAssessor` returns the
  byte-identical ``CloudAssessment`` the edge's own ``LocalCloudStub`` returns (drop-in guarantee).
  The edge package is imported via the sibling path (see ``conftest``); parity tests skip if it is
  not importable.
- **Personalization** — disease stage + fused baseline drift refine the considered level *upward*
  from the edge's level (a safety floor), never downward; the moderate / no-state path stays
  byte-identical to the edge stub.
"""

from __future__ import annotations

import json

import pytest

from airacare_care import ConsideredAssessor, DailyLivingEvent, PatientState
from airacare_care.contracts import utcnow

edge_stub = pytest.importorskip(
    "airacare_edge.cloud.stub", reason="edge package not importable from sibling path"
)
edge_contracts = pytest.importorskip("airacare_edge.cloud.contracts")

# Flagship edge decisions: ok -> L1, unclear -> L2, distress/no_response -> L3.
FLAGSHIP_CASES = [
    ("no_response", "L3", "escalated"),
    ("distress", "L3", "escalated"),
    ("unclear", "L2", "local_alert"),
    ("ok", "L1", "reassured"),
]


def _wander_event(
    response: str | None,
    level: str,
    action: str = "local_alert",
    *,
    baseline_deviation: float = 0.95,
) -> DailyLivingEvent:
    return DailyLivingEvent(
        type="wander",
        confidence=0.9,
        timestamp=utcnow(),
        patient_id="p-001",
        baseline_deviation=baseline_deviation,
        edge_assessed_level=level,  # type: ignore[arg-type]
        edge_action_taken=action,  # type: ignore[arg-type]
        context={"time_of_day": "night", "door_open": True, "response": response},
    )


def _state(stage: str, *, baseline_deviation: float = 0.0) -> PatientState:
    return PatientState(
        patient_id="p-001",
        disease_stage=stage,  # type: ignore[arg-type]
        baseline_deviation=baseline_deviation,
    )


def _edge_assessment(event: DailyLivingEvent):
    # Rebuild the event through the edge's own contracts (proves the copied contracts are
    # byte-compatible), then assess with the edge's stub.
    edge_event = edge_contracts.DailyLivingEvent.model_validate(json.loads(event.model_dump_json()))
    return edge_stub.LocalCloudStub().report(edge_event)


# --------------------------------------------------------------------------------------------
# Parity with the edge stub (drop-in guarantee)
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("response,level,action", FLAGSHIP_CASES)
def test_considered_assessment_matches_edge_stub(response: str, level: str, action: str) -> None:
    event = _wander_event(response, level, action)

    hosted = ConsideredAssessor().assess(event)  # no state -> parity path
    edge = _edge_assessment(event)

    assert hosted.considered_level == edge.considered_level == level
    assert hosted.model_dump_json() == edge.model_dump_json()


def test_l0_routine_parity() -> None:
    event = DailyLivingEvent(
        type="meal",
        confidence=0.5,
        timestamp=utcnow(),
        patient_id="p-001",
        baseline_deviation=0.1,
        edge_assessed_level="L0",
        edge_action_taken="none",
        context={"response": None},
    )
    hosted = ConsideredAssessor().assess(event)
    edge = _edge_assessment(event)

    assert hosted.considered_level == edge.considered_level == "L0"
    assert not hosted.caregiver_notifications
    assert hosted.model_dump_json() == edge.model_dump_json()


# --------------------------------------------------------------------------------------------
# Personalization (disease stage + fused baseline drift)
# --------------------------------------------------------------------------------------------


def test_severe_stage_escalates_unclear_wander() -> None:
    # unclear -> edge L2; a severe-stage patient with high nighttime drift is refined to L3.
    result = ConsideredAssessor().assess(_wander_event("unclear", "L2"), _state("severe"))

    assert result.considered_level == "L3"
    assert "refined from L2" in result.reason
    channels = [n.channel for n in result.caregiver_notifications]
    assert channels == ["family", "community"]


def test_severe_stage_does_not_escalate_reassured_patient() -> None:
    # response=ok means the patient explicitly reassured -> not escalated even for severe.
    result = ConsideredAssessor().assess(_wander_event("ok", "L1"), _state("severe"))

    assert result.considered_level == "L1"
    assert "refined" not in result.reason
    assert result.caregiver_notifications == []


def test_moderate_stage_preserves_edge_level() -> None:
    event = _wander_event("unclear", "L2")
    # moderate weight is 1.0 -> no refinement -> byte-identical to the no-state (parity) path.
    no_state = ConsideredAssessor().assess(event)
    moderate = ConsideredAssessor().assess(event, _state("moderate"))

    assert moderate.considered_level == "L2"
    assert moderate.model_dump_json() == no_state.model_dump_json()


def test_mild_stage_never_de_escalates() -> None:
    result = ConsideredAssessor().assess(_wander_event("unclear", "L2"), _state("mild"))
    # The edge level is a safety floor: mild weighting must not drop below it.
    assert result.considered_level == "L2"


def test_severe_stage_low_drift_stays_put() -> None:
    # High-risk gate needs real baseline drift; a low-drift event is not escalated.
    event = _wander_event("unclear", "L2", baseline_deviation=0.4)
    result = ConsideredAssessor().assess(event, _state("severe", baseline_deviation=0.4))
    assert result.considered_level == "L2"


def test_severe_fuses_persisted_baseline_drift() -> None:
    # Event drift alone is low, but the patient's persisted rolling baseline is high ->
    # the fused drift clears the bar and escalates.
    event = _wander_event("unclear", "L2", baseline_deviation=0.3)
    result = ConsideredAssessor().assess(event, _state("severe", baseline_deviation=0.95))
    assert result.considered_level == "L3"


@pytest.mark.parametrize("level,response", [("L3", "no_response"), ("L0", None)])
def test_extreme_levels_are_stable(level: str, response: str | None) -> None:
    # L3 is already the ceiling; L0 is not actionable -> neither moves.
    event = _wander_event(response, level, baseline_deviation=0.95)
    result = ConsideredAssessor().assess(event, _state("severe"))
    assert result.considered_level == level
