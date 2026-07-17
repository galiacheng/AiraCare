"""Parity: the Foundry considered assessor returns the same CloudAssessment as the edge stub.

This is the drop-in guarantee — for the flagship ``wander`` cases, the Foundry orchestrator
assesses identically to ``edge/airacare_edge/cloud/stub.py::LocalCloudStub``. The edge
package is imported via the sibling path (see conftest); tests skip if it isn't available.

Building the edge event from the Foundry event's serialized JSON also proves the copied
contracts are byte-compatible.
"""

from __future__ import annotations

import json

import pytest

from airacare_foundry.assess.assessor import ConsideredAssessor
from airacare_foundry.contracts import DailyLivingEvent, utcnow

edge_stub = pytest.importorskip(
    "airacare_edge.cloud.stub", reason="edge package not importable from sibling path"
)
edge_contracts = pytest.importorskip("airacare_edge.cloud.contracts")

# Flagship edge decisions: ok -> L1, unclear -> L2, distress/no_response -> L3
# (see edge/airacare_edge/reasoning/grader.py). The cloud echoes the edge's level.
FLAGSHIP_CASES = [
    ("no_response", "L3", "escalated"),
    ("distress", "L3", "escalated"),
    ("unclear", "L2", "local_alert"),
    ("ok", "L1", "reassured"),
]


def _wander_event(response: str, level: str, action: str) -> DailyLivingEvent:
    return DailyLivingEvent(
        type="wander",
        confidence=0.9,
        timestamp=utcnow(),
        patient_id="p-001",
        baseline_deviation=0.95,
        edge_assessed_level=level,  # type: ignore[arg-type]
        edge_action_taken=action,  # type: ignore[arg-type]
        context={"time_of_day": "night", "door_open": True, "response": response},
    )


def _edge_assessment(event: DailyLivingEvent):
    # Rebuild the event through the edge's own contracts (proves byte-compatibility).
    edge_event = edge_contracts.DailyLivingEvent.model_validate(json.loads(event.model_dump_json()))
    return edge_stub.LocalCloudStub().report(edge_event)


@pytest.mark.parametrize("response,level,action", FLAGSHIP_CASES)
def test_considered_assessment_matches_edge_stub(response: str, level: str, action: str) -> None:
    event = _wander_event(response, level, action)

    foundry_assessment = ConsideredAssessor().assess(event)
    edge_assessment = _edge_assessment(event)

    # Primary requirement: same considered level as the edge stub.
    assert foundry_assessment.considered_level == edge_assessment.considered_level == level
    # Stronger parity: the full CloudAssessment is identical on the wire.
    assert foundry_assessment.model_dump_json() == edge_assessment.model_dump_json()


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
    foundry_assessment = ConsideredAssessor().assess(event)
    edge_assessment = _edge_assessment(event)

    assert foundry_assessment.considered_level == edge_assessment.considered_level == "L0"
    assert not foundry_assessment.caregiver_notifications
    assert foundry_assessment.model_dump_json() == edge_assessment.model_dump_json()
