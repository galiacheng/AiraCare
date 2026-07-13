"""Split-screen panel renders without error and contains the key demo markers."""

from __future__ import annotations

import io
from datetime import datetime, timezone

from airacare_edge.agent import FlowResult
from airacare_edge.cloud.contracts import (
    CloudAction,
    CloudDecision,
    DailyLivingEvent,
    ReplyIntent,
)


def _result(offline: bool = False) -> FlowResult:
    event = DailyLivingEvent(
        type="wander",
        confidence=0.9,
        timestamp=datetime(2026, 7, 13, 3, 0, tzinfo=timezone.utc),
        patient_id="p-001",
        baseline_deviation=0.95,
        edge_action_taken="prompted" if not offline else "local_alert",
        context={"time_of_day": "night", "response": "no_response"},
    )
    if offline:
        return FlowResult(handled=True, path="offline_fallback", event=event,
                          reply=ReplyIntent(status="no_response"), cloud_decision=None, offline=True)
    decision = CloudDecision(
        grade="L3",
        reason="door open at night + no response -> high wandering risk",
        actions=[CloudAction(channel="family", message="check immediately")],
    )
    return FlowResult(handled=True, path="cloud_L3", event=event,
                      reply=ReplyIntent(status="no_response"), cloud_decision=decision, offline=False)


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


def test_panel_offline_shows_fallback():
    out = _render(_result(offline=True))
    assert "OFFLINE" in out.upper()
