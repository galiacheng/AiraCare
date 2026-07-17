"""Power BI export tests — flatten filed events to the dashboard CSV."""

from __future__ import annotations

import csv

from airacare_foundry.store.local import LocalEventStore
from airacare_foundry.tools.demo_seed import generate_events, to_records
from airacare_foundry.tools.powerbi_export import CSV_COLUMNS, export_csv, export_records


def test_export_records_writes_header_and_rows(tmp_path) -> None:
    records = to_records(generate_events())
    out = export_records(records, tmp_path / "sample_events.csv")

    with out.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert list(rows[0].keys()) == CSV_COLUMNS
    assert len(rows) == len(records) == 38


def test_export_biomarker_and_levels_present(tmp_path) -> None:
    records = to_records(generate_events())
    out = export_records(records, tmp_path / "e.csv")
    with out.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    first = rows[0]
    assert first["type"] == "routine"
    assert first["considered_level"] in {"L0", "L1", "L2", "L3"}
    assert 0.0 <= float(first["biomarker"]) <= 1.0


def test_export_csv_from_store(tmp_path) -> None:
    store = LocalEventStore(":memory:")
    for r in to_records(generate_events()):
        store.append(r)
    out = export_csv(store, "p-001", tmp_path / "store.csv")
    with out.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 38
    # wander context flags survive the flattening
    wander_rows = [r for r in rows if r["type"] == "wander"]
    assert wander_rows and all(r["door_open"] == "True" for r in wander_rows)
