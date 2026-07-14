"""Split-screen panel renders without error and contains the key demo markers."""

from __future__ import annotations

import io
from datetime import datetime, timezone

from airacare_edge.agent import FlowResult
from airacare_edge.cloud.contracts import (
    CloudAction,
    CloudAssessment,
    DailyLivingEvent,
    ReplyIntent,
)
from airacare_edge.reasoning.grader import EdgeDecision


def _result(offline: bool = False) -> FlowResult:
    event = DailyLivingEvent(
        type="wander",
        confidence=0.9,
        timestamp=datetime(2026, 7, 13, 3, 0, tzinfo=timezone.utc),
        patient_id="p-001",
        baseline_deviation=0.95,
        edge_assessed_level="L3",
        edge_action_taken="escalated",
        context={"time_of_day": "night", "response": "no_response"},
    )
    decision = EdgeDecision(level="L3", action="escalated", reason="no response -> escalate")
    if offline:
        return FlowResult(handled=True, path="edge_L3", event=event,
                          reply=ReplyIntent(status="no_response"), decision=decision,
                          assessment=None, reported=False)
    assessment = CloudAssessment(
        considered_level="L3",
        reason="door open at night + no response -> high wandering risk",
        caregiver_notifications=[CloudAction(channel="family", message="check immediately")],
        policy_version=1,
    )
    return FlowResult(handled=True, path="edge_L3", event=event,
                      reply=ReplyIntent(status="no_response"), decision=decision,
                      assessment=assessment, reported=True)


def _render(result: FlowResult, provenance=None) -> str:
    from rich.console import Console

    from airacare_edge.ui.panel import render_split

    buf = io.StringIO()
    console = Console(file=buf, width=140, force_terminal=False, color_system=None)
    render_split(console, result, sensors=["out_of_bed", "door_open"], provenance=provenance, cloud_mode="a2a")
    return buf.getvalue()


def test_panel_online_l3_markers():
    out = _render(_result())
    assert "EDGE" in out
    assert "FOUNDRY" in out
    assert "L3" in out
    assert "DailyLivingEvent" in out
    assert "no raw audio" in out.lower()


def test_panel_shows_llm_provenance():
    prov = {"keyword": "unclear", "llm_used": True, "llm_result": "distress", "final": "distress"}
    out = _render(_result(), provenance=prov)
    assert "LLM" in out


def test_panel_offline_shows_queued():
    out = _render(_result(offline=True))
    assert "OFFLINE" in out.upper()
