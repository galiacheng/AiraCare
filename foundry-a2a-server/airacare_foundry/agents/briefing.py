"""Briefing agent — family daily + clinician monthly reports from filed events (T2).

Reads the :class:`~airacare_foundry.store.base.EventStore` (privacy-scrubbed events only) and
composes two audiences:

- **Family daily** — a short, plain-language, reassuring recap of the day's events.
- **Clinician monthly** — a clinical roll-up over the month with event/level counts and the
  embedded :class:`~airacare_foundry.agents.cognitive_trend.CognitiveTrend`.

Both are batch/off the safety path; they enrich caregiver comms and the Power BI dashboard.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field

from airacare_foundry.agents.cognitive_trend import CognitiveTrend, CognitiveTrendAgent
from airacare_foundry.store.base import EventStore, RecordedEvent

Audience = Literal["family", "clinician"]

# Human-readable, plain-language labels for the flagship event types (family briefing).
_TYPE_LABEL = {
    "wander": "wandering",
    "fall": "a possible fall",
    "med": "a medication moment",
    "meal": "a meal",
    "routine": "routine activity",
}
_LEVEL_LABEL = {"L0": "logged", "L1": "gentle check", "L2": "alerted", "L3": "escalated"}


class Briefing(BaseModel):
    """A generated report for a given audience over a time window."""

    patient_id: str
    audience: Audience
    period: str  # e.g. "2026-07-15" (daily) or "2026-07" (monthly)
    window_start: datetime
    window_end: datetime
    event_count: int = 0
    counts_by_type: dict[str, int] = Field(default_factory=dict)
    counts_by_level: dict[str, int] = Field(default_factory=dict)
    highlights: list[str] = Field(default_factory=list)
    trend: CognitiveTrend | None = None
    summary: str = ""


class BriefingAgent:
    """Composes family-daily and clinician-monthly briefings from filed events."""

    def __init__(
        self,
        event_store: EventStore,
        trend_agent: CognitiveTrendAgent | None = None,
        *,
        enabled: bool = True,
    ) -> None:
        self._store = event_store
        self._trend = trend_agent or CognitiveTrendAgent(event_store)
        self.enabled = enabled

    def family_daily(self, patient_id: str, day: date | None = None) -> Briefing:
        """A reassuring plain-language recap of a single day (UTC)."""
        day = day or datetime.now(timezone.utc).date()
        start = datetime.combine(day, time.min, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        records = self._store.list_for_patient(patient_id, since=start, until=end)

        by_type, by_level = self._counts(records)
        highlights = [self._family_line(r) for r in records if r.considered_level != "L0"]
        summary = self._family_summary(patient_id, records, by_level)
        return Briefing(
            patient_id=patient_id,
            audience="family",
            period=day.isoformat(),
            window_start=start,
            window_end=end,
            event_count=len(records),
            counts_by_type=by_type,
            counts_by_level=by_level,
            highlights=highlights,
            summary=summary,
        )

    def clinician_monthly(self, patient_id: str, year: int, month: int) -> Briefing:
        """A clinical roll-up over a calendar month, including the cognitive trajectory."""
        start = datetime(year, month, 1, tzinfo=timezone.utc)
        end = (
            datetime(year + 1, 1, 1, tzinfo=timezone.utc)
            if month == 12
            else datetime(year, month + 1, 1, tzinfo=timezone.utc)
        )
        records = self._store.list_for_patient(patient_id, since=start, until=end)

        by_type, by_level = self._counts(records)
        trend = self._trend.analyze(patient_id, since=start, until=end)
        highlights = self._clinician_highlights(by_type, by_level, trend)
        summary = self._clinician_summary(patient_id, records, trend)
        return Briefing(
            patient_id=patient_id,
            audience="clinician",
            period=f"{year:04d}-{month:02d}",
            window_start=start,
            window_end=end,
            event_count=len(records),
            counts_by_type=by_type,
            counts_by_level=by_level,
            highlights=highlights,
            trend=trend,
            summary=summary,
        )

    @staticmethod
    def _counts(records: list[RecordedEvent]) -> tuple[dict[str, int], dict[str, int]]:
        by_type: dict[str, int] = {}
        by_level: dict[str, int] = {}
        for r in records:
            by_type[r.event.type] = by_type.get(r.event.type, 0) + 1
            by_level[r.considered_level] = by_level.get(r.considered_level, 0) + 1
        return by_type, by_level

    @staticmethod
    def _family_line(record: RecordedEvent) -> str:
        when = record.event.timestamp.strftime("%H:%M")
        what = _TYPE_LABEL.get(record.event.type, record.event.type)
        did = _LEVEL_LABEL.get(record.considered_level, record.considered_level)
        return f"{when} — {what} ({did})"

    @staticmethod
    def _family_summary(
        patient_id: str, records: list[RecordedEvent], by_level: dict[str, int]
    ) -> str:
        if not records:
            return "A calm day — no notable events were recorded."
        concerns = sum(by_level.get(lvl, 0) for lvl in ("L2", "L3"))
        if concerns == 0:
            return (
                f"A settled day with {len(records)} everyday moments and nothing that "
                "needed a caregiver alert."
            )
        return (
            f"{len(records)} moments today; {concerns} needed a caregiver alert. "
            "See the highlights below."
        )

    @staticmethod
    def _clinician_highlights(
        by_type: dict[str, int], by_level: dict[str, int], trend: CognitiveTrend
    ) -> list[str]:
        highlights = [f"Cognitive trajectory: {trend.summary}"]
        wanders = by_type.get("wander", 0)
        if wanders:
            highlights.append(f"{wanders} wandering event(s) this month.")
        escalated = by_level.get("L3", 0)
        if escalated:
            highlights.append(f"{escalated} event(s) reached L3 escalation.")
        return highlights

    @staticmethod
    def _clinician_summary(
        patient_id: str, records: list[RecordedEvent], trend: CognitiveTrend
    ) -> str:
        if not records:
            return "No events filed this month; cognitive trajectory indeterminate."
        return (
            f"{len(records)} events filed this month for {patient_id}. "
            f"Voice-biomarker trajectory is {trend.direction} "
            f"({trend.slope_per_day:+.4f} index/day, n={trend.n_samples})."
        )


__all__ = ["Audience", "Briefing", "BriefingAgent"]
