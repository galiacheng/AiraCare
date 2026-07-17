"""Power BI export — flatten filed events into a CSV the dashboard ingests.

Decision #6 = C: for the hackathon we don't stand up the full Cosmos DB → Fabric/OneLake →
Power BI pipeline. Instead we export the same privacy-scrubbed :class:`RecordedEvent`s to a flat
CSV that a **Power BI** report loads directly, standing in for the OneLake mirror. The columns
are chosen to drive the pitch dashboard visuals (see ``foundry-a2a-server/powerbi/README.md``): the
cognitive trajectory line, the event-type mix, the escalation funnel, and the daily volume.

Privacy invariant holds: only derived event data is exported — never raw audio/video/features
beyond the single reduced voice-biomarker index.
"""

from __future__ import annotations

import csv
from pathlib import Path

from airacare_foundry.agents.cognitive_trend import default_biomarker
from airacare_foundry.store.base import EventStore, RecordedEvent

CSV_COLUMNS = [
    "date",
    "time",
    "timestamp",
    "patient_id",
    "type",
    "considered_level",
    "edge_assessed_level",
    "baseline_deviation",
    "biomarker",
    "time_of_day",
    "door_open",
    "response",
]


def record_to_row(record: RecordedEvent) -> dict[str, object]:
    """Flatten one recorded event into a Power BI-friendly row."""
    event = record.event
    ctx = event.context
    return {
        "date": event.timestamp.date().isoformat(),
        "time": event.timestamp.strftime("%H:%M"),
        "timestamp": event.timestamp.isoformat(),
        "patient_id": event.patient_id,
        "type": event.type,
        "considered_level": record.considered_level,
        "edge_assessed_level": event.edge_assessed_level,
        "baseline_deviation": round(event.baseline_deviation, 4),
        "biomarker": round(default_biomarker(record), 4),
        "time_of_day": ctx.get("time_of_day", ""),
        "door_open": bool(ctx.get("door_open", False)),
        "response": ctx.get("response", ""),
    }


def export_records(records: list[RecordedEvent], out_path: str | Path) -> Path:
    """Write recorded events to ``out_path`` as CSV; returns the written path."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for record in records:
            writer.writerow(record_to_row(record))
    return out


def export_csv(event_store: EventStore, patient_id: str, out_path: str | Path) -> Path:
    """Read a patient's filed events from the store and export them to CSV."""
    return export_records(event_store.list_for_patient(patient_id), out_path)


__all__ = ["CSV_COLUMNS", "record_to_row", "export_records", "export_csv"]
