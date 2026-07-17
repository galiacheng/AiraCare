"""Dashboard data layer — filed events → the dashboard JSON payload (backend-agnostic).

:class:`DashboardData` wraps any :class:`~airacare_foundry.store.base.EventStore` (local SQLite or
Cosmos) plus the patient-state store and reuses the **same** Cognitive-Trend and Briefing agents
the orchestrator uses, so every number on the dashboard matches the rest of the system. It never
touches the real-time safety path — it only *reads* the append-only event log.

The visuals it drives (see ``powerbi/README.md`` for the original pitch framing):

1. **Cognitive trajectory** — per-event voice-biomarker index over time + the OLS trend line.
2. **Event mix** — event-type counts bucketed by ISO week.
3. **Escalation funnel** — considered-level distribution and an edge-vs-cloud level comparison.
4. **Nighttime risk** — wander events at night with the door open (the elopement signal).

Privacy invariant: only derived :class:`~airacare_foundry.store.base.RecordedEvent` data is read.
"""

from __future__ import annotations

from datetime import datetime, timezone

from airacare_foundry.agents.briefing import Briefing, BriefingAgent
from airacare_foundry.agents.cognitive_trend import CognitiveTrendAgent, default_biomarker
from airacare_foundry.store.base import EventStore, PatientStateStore, RecordedEvent
from airacare_foundry.tools.powerbi_export import record_to_row

# Stable ordering for the categorical axes so colors/legends stay put across refreshes.
EVENT_TYPES = ["routine", "wander", "med", "meal", "fall"]
LEVELS = ["L0", "L1", "L2", "L3"]


def _week_label(ts: datetime) -> str:
    """ISO calendar week label, e.g. ``2026-W29`` — the event-mix / nighttime bucket key."""
    iso = ts.isocalendar()
    return f"{iso[0]:04d}-W{iso[1]:02d}"


class DashboardData:
    """Turns a patient's filed events into the dashboard payload.

    Backend-agnostic: pass the ``local`` or ``cosmos`` stores built by
    :func:`~airacare_foundry.orchestrator._build_stores`. All computation is read-only.
    """

    def __init__(
        self,
        event_store: EventStore,
        state_store: PatientStateStore,
        *,
        default_patient_id: str,
        backend: str = "local",
    ) -> None:
        self._events = event_store
        self._state = state_store
        self._default_patient_id = default_patient_id
        self._backend = backend
        self._trend = CognitiveTrendAgent(event_store)
        self._briefing = BriefingAgent(event_store, self._trend)

    # -- helpers ---------------------------------------------------------------------------

    def _records(self, patient_id: str) -> list[RecordedEvent]:
        return self._events.list_for_patient(patient_id)

    @staticmethod
    def _sorted_weeks(records: list[RecordedEvent]) -> list[str]:
        return sorted({_week_label(r.event.timestamp) for r in records})

    # -- individual panels -----------------------------------------------------------------

    def trend_series(self, records: list[RecordedEvent]) -> dict:
        """Cognitive-trajectory scatter + the ordinary-least-squares fit line."""
        points = [
            {"t": r.event.timestamp.isoformat(), "y": round(default_biomarker(r), 4)}
            for r in records
        ]
        trend = self._trend.analyze(records[0].event.patient_id) if records else None
        fit: list[dict] = []
        if len(records) >= 2:
            origin = records[0].event.timestamp
            xs = [(r.event.timestamp - origin).total_seconds() / 86400.0 for r in records]
            ys = [default_biomarker(r) for r in records]
            n = len(xs)
            mean_x = sum(xs) / n
            mean_y = sum(ys) / n
            var_x = sum((x - mean_x) ** 2 for x in xs)
            slope = (
                sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / var_x
                if var_x
                else 0.0
            )
            intercept = mean_y - slope * mean_x
            fit = [
                {"t": records[0].event.timestamp.isoformat(), "y": round(intercept, 4)},
                {
                    "t": records[-1].event.timestamp.isoformat(),
                    "y": round(intercept + slope * xs[-1], 4),
                },
            ]
        return {
            "points": points,
            "fit": fit,
            "direction": trend.direction if trend else "unknown",
            "slope_per_day": trend.slope_per_day if trend else 0.0,
            "slope_per_week": round(trend.slope_per_day * 7.0, 4) if trend else 0.0,
            "latest_score": trend.latest_score if trend else None,
            "mean_score": trend.mean_score if trend else None,
            "summary": trend.summary if trend else "no data",
        }

    def event_mix(self, records: list[RecordedEvent]) -> dict:
        """Event-type counts bucketed by ISO week (stacked-column source)."""
        weeks = self._sorted_weeks(records)
        index = {w: i for i, w in enumerate(weeks)}
        counts: dict[str, list[int]] = {t: [0] * len(weeks) for t in EVENT_TYPES}
        for r in records:
            etype = r.event.type if r.event.type in counts else "routine"
            counts[etype][index[_week_label(r.event.timestamp)]] += 1
        return {"weeks": weeks, "types": EVENT_TYPES, "counts": counts}

    def escalation_funnel(self, records: list[RecordedEvent]) -> dict:
        """Considered-level distribution + the edge's own grade for the same events."""
        cloud = {lvl: 0 for lvl in LEVELS}
        edge = {lvl: 0 for lvl in LEVELS}
        refined = 0
        for r in records:
            if r.considered_level in cloud:
                cloud[r.considered_level] += 1
            if r.event.edge_assessed_level in edge:
                edge[r.event.edge_assessed_level] += 1
            if r.considered_level != r.event.edge_assessed_level:
                refined += 1
        return {
            "levels": LEVELS,
            "cloud": [cloud[lvl] for lvl in LEVELS],
            "edge": [edge[lvl] for lvl in LEVELS],
            "refined_count": refined,
        }

    def nighttime_risk(self, records: list[RecordedEvent]) -> dict:
        """Weekly count of nighttime wanders with the door open — the elopement signal."""
        weeks = self._sorted_weeks(records)
        index = {w: i for i, w in enumerate(weeks)}
        counts = [0] * len(weeks)
        total = 0
        for r in records:
            ctx = r.event.context
            if (
                r.event.type == "wander"
                and ctx.get("time_of_day") == "night"
                and bool(ctx.get("door_open", False))
            ):
                counts[index[_week_label(r.event.timestamp)]] += 1
                total += 1
        return {"weeks": weeks, "counts": counts, "total": total}

    def events_table(self, records: list[RecordedEvent], *, limit: int = 200) -> list[dict]:
        """Flattened, Power BI-shaped rows for the raw-events table (most recent first)."""
        rows = [record_to_row(r) for r in records]
        rows.reverse()
        return rows[:limit]

    def _latest_day(self, records: list[RecordedEvent]) -> datetime:
        return records[-1].event.timestamp if records else datetime.now(timezone.utc)

    def family_briefing(self, patient_id: str, records: list[RecordedEvent]) -> Briefing:
        """Family daily recap for the patient's most recent event day (never a blank 'today')."""
        return self._briefing.family_daily(patient_id, self._latest_day(records).date())

    def clinician_briefing(self, patient_id: str, records: list[RecordedEvent]) -> Briefing:
        """Clinician monthly roll-up for the patient's most recent event month."""
        latest = self._latest_day(records)
        return self._briefing.clinician_monthly(patient_id, latest.year, latest.month)

    def summary(self, patient_id: str, records: list[RecordedEvent], trend: dict) -> dict:
        """Headline KPIs shown as cards above the charts."""
        state = self._state.get(patient_id)
        by_level = {lvl: 0 for lvl in LEVELS}
        for r in records:
            if r.considered_level in by_level:
                by_level[r.considered_level] += 1
        nights = self.nighttime_risk(records)
        funnel = self.escalation_funnel(records)
        window = {
            "start": records[0].event.timestamp.date().isoformat() if records else None,
            "end": records[-1].event.timestamp.date().isoformat() if records else None,
        }
        return {
            "patient_id": patient_id,
            "patient_name": state.name if state else patient_id,
            "disease_stage": state.disease_stage if state else "unknown",
            "backend": self._backend,
            "event_count": len(records),
            "counts_by_level": by_level,
            "escalations": by_level["L3"],
            "nighttime_risk": nights["total"],
            "refined_count": funnel["refined_count"],
            "trend_direction": trend["direction"],
            "trend_slope_per_week": trend["slope_per_week"],
            "latest_score": trend["latest_score"],
            "mean_score": trend["mean_score"],
            "window": window,
        }

    # -- aggregate -------------------------------------------------------------------------

    def snapshot(self, patient_id: str | None = None) -> dict:
        """The full dashboard payload for one patient — a single fetch drives the whole page."""
        pid = patient_id or self._default_patient_id
        records = self._records(pid)
        trend = self.trend_series(records)
        return {
            "patient_id": pid,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": self.summary(pid, records, trend),
            "trend": trend,
            "event_mix": self.event_mix(records),
            "funnel": self.escalation_funnel(records),
            "nighttime": self.nighttime_risk(records),
            "events": self.events_table(records),
            "briefings": {
                "family": self.family_briefing(pid, records).model_dump(mode="json"),
                "clinician": self.clinician_briefing(pid, records).model_dump(mode="json"),
            },
        }


__all__ = ["DashboardData", "EVENT_TYPES", "LEVELS"]
