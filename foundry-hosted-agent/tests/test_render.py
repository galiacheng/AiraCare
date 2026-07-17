"""The deterministic wire channel: render a CloudAssessment into a block the edge parses back.

``render_assessment_block`` / ``parse_assessment_block`` are the fallback that guarantees the
considered level survives the trip back to the edge over standard A2A even if Foundry's A2A
projection does not preserve a structured DataPart: the middleware appends a delimited
``CONSIDERED ASSESSMENT (JSON)`` block after the model's warm narration, and the edge decodes the
JSON immediately after the marker. These tests pin that round-trip and its robustness.
"""

from __future__ import annotations

from airacare_care import (
    ASSESSMENT_MARKER,
    ConsideredAssessor,
    DailyLivingEvent,
    PatientState,
    parse_assessment_block,
    render_assessment_block,
)
from airacare_care.contracts import CloudAction, CloudAssessment, utcnow


def _severe_l3_assessment() -> CloudAssessment:
    event = DailyLivingEvent(
        type="wander",
        confidence=0.9,
        timestamp=utcnow(),
        patient_id="p-001",
        baseline_deviation=0.95,
        edge_assessed_level="L2",
        edge_action_taken="local_alert",
        context={"time_of_day": "night", "door_open": True, "response": "unclear"},
    )
    return ConsideredAssessor().assess(
        event, PatientState(patient_id="p-001", disease_stage="severe")
    )


def test_round_trips_a_refined_assessment() -> None:
    original = _severe_l3_assessment()
    block = render_assessment_block(original)

    parsed = parse_assessment_block(block)
    assert parsed is not None
    # Full fidelity: the decoded assessment is byte-identical to the original on the wire.
    assert parsed.model_dump_json() == original.model_dump_json()
    assert parsed.considered_level == "L3"
    assert [n.channel for n in parsed.caregiver_notifications] == ["family", "community"]


def test_survives_embedding_in_model_narration() -> None:
    # The real turn is "<warm narration>\n<block>"; the edge must still find the verdict.
    original = _severe_l3_assessment()
    wire = "Rose seems restless tonight; I've alerted the family and the neighborhood watch.\n"
    wire += render_assessment_block(original)

    parsed = parse_assessment_block(wire)
    assert parsed is not None
    assert parsed.considered_level == original.considered_level


def test_block_carries_the_marker_and_valid_json_after_it() -> None:
    block = render_assessment_block(_severe_l3_assessment())
    assert block.startswith(ASSESSMENT_MARKER)
    # The JSON begins at the first brace after the marker.
    assert "{" in block[len(ASSESSMENT_MARKER):]


def test_missing_marker_returns_none() -> None:
    assert parse_assessment_block("just a warm conversational reply, no verdict here") is None


def test_malformed_payload_returns_none() -> None:
    assert parse_assessment_block(f"{ASSESSMENT_MARKER}\n{{not valid json") is None


def test_payload_without_considered_level_returns_none() -> None:
    assert parse_assessment_block(f'{ASSESSMENT_MARKER}\n{{"foo": 1}}') is None


def test_trailing_text_after_json_is_ignored() -> None:
    # raw_decode stops at the end of the JSON object; trailing prose does not break parsing.
    original = _severe_l3_assessment()
    wire = render_assessment_block(original) + "\n\n(Let me know if you'd like more detail.)"
    parsed = parse_assessment_block(wire)
    assert parsed is not None
    assert parsed.considered_level == original.considered_level


def test_l0_assessment_round_trips_with_no_notifications() -> None:
    assessment = CloudAssessment(considered_level="L0", reason="routine")
    parsed = parse_assessment_block(render_assessment_block(assessment))
    assert parsed is not None
    assert parsed.considered_level == "L0"
    assert parsed.caregiver_notifications == []


def test_notifications_survive_the_round_trip() -> None:
    assessment = CloudAssessment(
        considered_level="L3",
        reason="manual",
        caregiver_notifications=[
            CloudAction(channel="family", message="check on Rose", target="+1-555-0100"),
            CloudAction(channel="community", message="please look in", target="watch"),
        ],
    )
    parsed = parse_assessment_block(render_assessment_block(assessment))
    assert parsed is not None
    assert [(n.channel, n.target) for n in parsed.caregiver_notifications] == [
        ("family", "+1-555-0100"),
        ("community", "watch"),
    ]
