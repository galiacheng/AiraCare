"""Briefing agent tests — family daily + clinician monthly from filed events."""

from __future__ import annotations

from datetime import date

from airacare_foundry.agents.briefing import BriefingAgent
from airacare_foundry.store.local import LocalEventStore
from airacare_foundry.tools.demo_seed import generate_events, to_records


def _seeded_store() -> LocalEventStore:
    store = LocalEventStore(":memory:")
    for r in to_records(generate_events()):  # 2026-06-16 .. 2026-07-15
        store.append(r)
    return store


def test_family_daily_on_a_wander_day() -> None:
    briefing = BriefingAgent(_seeded_store()).family_daily("p-001", date(2026, 7, 6))
    assert briefing.audience == "family"
    assert briefing.period == "2026-07-06"
    assert briefing.event_count == 2  # morning routine + nighttime wander
    assert briefing.counts_by_type == {"routine": 1, "wander": 1}
    assert any("wandering" in h for h in briefing.highlights)
    assert "alert" in briefing.summary


def test_family_daily_quiet_day_has_no_highlights() -> None:
    briefing = BriefingAgent(_seeded_store()).family_daily("p-001", date(2026, 7, 7))
    assert briefing.event_count == 1  # routine only
    assert briefing.highlights == []
    assert "settled" in briefing.summary.lower() or "calm" in briefing.summary.lower()


def test_family_daily_empty_day() -> None:
    briefing = BriefingAgent(LocalEventStore(":memory:")).family_daily("p-001", date(2026, 7, 7))
    assert briefing.event_count == 0
    assert "calm day" in briefing.summary.lower()


def test_clinician_monthly_rolls_up_july() -> None:
    briefing = BriefingAgent(_seeded_store()).clinician_monthly("p-001", 2026, 7)
    assert briefing.audience == "clinician"
    assert briefing.period == "2026-07"
    assert briefing.event_count == 19  # 15 routine + 3 wander + 1 med (2026-07-01..07-15)
    assert briefing.counts_by_type.get("wander") == 3
    assert briefing.trend is not None
    assert briefing.trend.direction == "declining"
    assert any("trajectory" in h.lower() for h in briefing.highlights)


def test_clinician_monthly_empty_month() -> None:
    briefing = BriefingAgent(_seeded_store()).clinician_monthly("p-001", 2020, 1)
    assert briefing.event_count == 0
    assert briefing.trend is not None
    assert "indeterminate" in briefing.summary
