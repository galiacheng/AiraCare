"""Tests for the care dashboard — data layer + the stdlib HTTP server.

Offline and network-free: the data layer is exercised over a seeded in-memory ``LocalEventStore``
and the server is smoke-tested on an ephemeral port with ``urllib``. The front-end (Chart.js via
CDN) is out of scope — these tests cover the JSON the page consumes.
"""

from __future__ import annotations

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from airacare_dashboard.config import DashboardConfig, PatientConfig
from airacare_dashboard.data import EVENT_TYPES, LEVELS, DashboardData
from airacare_dashboard.seed import DEFAULT_PATIENT_ID, seed_event_store
from airacare_dashboard.server import _make_handler, build_data
from airacare_dashboard.stores import LocalEventStore, seeded_local_store

PATIENT = DEFAULT_PATIENT_ID


@pytest.fixture()
def data() -> DashboardData:
    events = LocalEventStore(":memory:")
    seed_event_store(events, patient_id=PATIENT, days=30)
    state = seeded_local_store(
        ":memory:", patient_id=PATIENT, name="Grandpa Zhang", disease_stage="moderate"
    )
    return DashboardData(events, state, default_patient_id=PATIENT, backend="local")


def test_snapshot_has_all_panels(data: DashboardData) -> None:
    snap = data.snapshot()
    assert snap["patient_id"] == PATIENT
    for key in ("summary", "trend", "event_mix", "funnel", "nighttime", "events", "briefings"):
        assert key in snap, key


def test_summary_kpis(data: DashboardData) -> None:
    s = data.snapshot()["summary"]
    assert s["patient_name"] == "Grandpa Zhang"
    assert s["disease_stage"] == "moderate"
    assert s["backend"] == "local"
    assert s["event_count"] > 30  # daily routine + wanders + occasional med over the month
    assert set(s["counts_by_level"]) == set(LEVELS)
    assert s["window"]["start"] and s["window"]["end"]


def test_trend_is_declining_with_fit_line(data: DashboardData) -> None:
    t = data.snapshot()["trend"]
    assert t["direction"] == "declining"  # demo seed encodes a gently declining biomarker
    assert t["slope_per_week"] < 0
    assert len(t["points"]) > 30
    assert len(t["fit"]) == 2  # OLS endpoints
    assert 0.0 <= t["points"][0]["y"] <= 1.0


def test_event_mix_weeks_align(data: DashboardData) -> None:
    m = data.snapshot()["event_mix"]
    assert m["types"] == EVENT_TYPES
    assert m["weeks"]
    for series in m["counts"].values():
        assert len(series) == len(m["weeks"])
    # Every filed event lands in exactly one (type, week) bucket.
    total = sum(sum(series) for series in m["counts"].values())
    assert total == data.snapshot()["summary"]["event_count"]


def test_funnel_edge_vs_cloud(data: DashboardData) -> None:
    f = data.snapshot()["funnel"]
    assert f["levels"] == LEVELS
    assert sum(f["cloud"]) == sum(f["edge"])  # same events graded twice
    assert f["refined_count"] >= 0


def test_nighttime_risk_counts_wanders(data: DashboardData) -> None:
    nt = data.snapshot()["nighttime"]
    # Demo seed: a night wander with door_open every 5th day over 30 days -> 6.
    assert nt["total"] == 6
    assert sum(nt["counts"]) == nt["total"]


def test_briefings_present(data: DashboardData) -> None:
    b = data.snapshot()["briefings"]
    assert b["family"]["audience"] == "family"
    assert b["clinician"]["audience"] == "clinician"
    assert b["clinician"]["trend"]["direction"] == "declining"


def test_empty_store_is_safe() -> None:
    empty = DashboardData(
        LocalEventStore(":memory:"),
        seeded_local_store(":memory:", patient_id=PATIENT, name="Nobody"),
        default_patient_id=PATIENT,
        backend="local",
    )
    snap = empty.snapshot()
    assert snap["summary"]["event_count"] == 0
    assert snap["trend"]["points"] == []
    assert snap["nighttime"]["total"] == 0
    assert snap["events"] == []


def _serve(handler) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def test_http_healthz_and_dashboard() -> None:
    config = DashboardConfig(patient=PatientConfig(id=PATIENT, name="Grandpa Zhang"))
    data = build_data(config, seed=True, days=30)
    httpd = _serve(_make_handler(data))
    try:
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        with urllib.request.urlopen(base + "/healthz") as resp:
            assert resp.status == 200
            assert json.loads(resp.read())["status"] == "ok"
        with urllib.request.urlopen(base + "/api/dashboard") as resp:
            assert resp.status == 200
            payload = json.loads(resp.read())
        assert payload["summary"]["event_count"] > 30
        assert payload["nighttime"]["total"] == 6
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_index_and_static_served() -> None:
    config = DashboardConfig(patient=PatientConfig(id=PATIENT, name="Grandpa Zhang"))
    httpd = _serve(_make_handler(build_data(config, seed=True, days=7)))
    try:
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        with urllib.request.urlopen(base + "/") as resp:
            assert resp.status == 200
            assert b"AiraCare" in resp.read()
        with urllib.request.urlopen(base + "/static/app.js") as resp:
            assert resp.status == 200
            assert "javascript" in resp.headers.get("Content-Type", "")
    finally:
        httpd.shutdown()
        httpd.server_close()
