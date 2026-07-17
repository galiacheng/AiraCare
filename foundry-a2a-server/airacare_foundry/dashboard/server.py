"""Foundry dashboard server — a stdlib HTTP app that serves the live care dashboard.

Same dependency-light pattern as :mod:`airacare_foundry.a2a_server` (stdlib
:class:`http.server`, **no web framework**): it builds the configured event/state stores (local
SQLite or Cosmos), wraps them in :class:`~airacare_foundry.dashboard.data.DashboardData`, and
serves a single-page front-end plus one JSON API.

Routes:

- ``GET /``                       -> the dashboard HTML page
- ``GET /static/<file>``          -> the page's CSS/JS assets
- ``GET /healthz``                -> ``{"status": "ok"}`` (liveness)
- ``GET /api/dashboard[?patient_id=]`` -> the full :meth:`DashboardData.snapshot` payload

Run standalone::

    python -m airacare_foundry.dashboard.server --config config.yaml --seed
    python -m airacare_foundry.dashboard.server --config config.yaml --backend cosmos --port 8973

``--seed`` writes the deterministic demo month into the configured event store first, so the
in-memory local demo lights up immediately (a no-op safety net if the store already has data).
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from airacare_foundry.dashboard.data import DashboardData

_STATIC_DIR = Path(__file__).parent / "static"
_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
}


def _make_handler(data: DashboardData) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        # Keep the demo console quiet; the dashboard is a read-only analytics surface.
        def log_message(self, *_args: object) -> None:  # noqa: D401 (silence default logging)
            return

        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            parsed = urlparse(self.path)
            route = parsed.path.rstrip("/") or "/"
            if route in ("/healthz", "/health"):
                self._json(200, {"status": "ok"})
            elif route == "/":
                self._static("index.html")
            elif route == "/api/dashboard":
                self._dashboard(parse_qs(parsed.query))
            elif parsed.path.startswith("/static/"):
                self._static(Path(parsed.path).name)
            else:
                self._json(404, {"error": "not found"})

        # -- handlers ------------------------------------------------------------------

        def _dashboard(self, query: dict[str, list[str]]) -> None:
            patient_id = query.get("patient_id", [None])[0]
            try:
                payload = data.snapshot(patient_id)
            except Exception as exc:  # pragma: no cover - defensive; surfaced to the page
                self._json(500, {"error": str(exc)})
                return
            self._json(200, payload)

        def _static(self, name: str) -> None:
            # Resolve within the static dir only — never serve outside the package.
            target = (_STATIC_DIR / name).resolve()
            if _STATIC_DIR.resolve() not in target.parents or not target.is_file():
                self._json(404, {"error": "not found"})
                return
            body = target.read_bytes()
            ctype = _CONTENT_TYPES.get(target.suffix, "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: object) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return _Handler


def build_data(config, *, seed: bool, days: int) -> DashboardData:
    """Build :class:`DashboardData` from a loaded config, optionally seeding demo events."""
    from airacare_foundry.orchestrator import _build_stores

    state_store, event_store = _build_stores(config)
    if seed:
        from airacare_foundry.tools.demo_seed import seed_event_store

        # Idempotent-ish for the demo: only seed when the patient has no filed events yet.
        if not event_store.list_for_patient(config.patient.id):
            seed_event_store(event_store, patient_id=config.patient.id, days=days)
    return DashboardData(
        event_store,
        state_store,
        default_patient_id=config.patient.id,
        backend=config.store.backend,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point — build the dashboard data and serve it over HTTP."""
    import argparse

    from airacare_foundry.config import FoundryConfig

    parser = argparse.ArgumentParser(
        prog="python -m airacare_foundry.dashboard.server",
        description="Serve the AiraCare live care dashboard (reads the filed EventStore).",
    )
    parser.add_argument("--config", help="Path to config.yaml (defaults to the demo patient).")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8973, help="Bind port (default 8973).")
    parser.add_argument(
        "--backend",
        choices=["local", "cosmos"],
        help="Override store.backend from the config.",
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Seed the deterministic demo month if the event store is empty.",
    )
    parser.add_argument("--days", type=int, default=30, help="Days of demo history to seed.")
    args = parser.parse_args(argv)

    if args.config:
        config = FoundryConfig.load(args.config)
    else:
        from airacare_foundry.config import PatientConfig

        config = FoundryConfig(patient=PatientConfig(id="p-001", name="Grandpa Zhang"))
    if args.backend:
        config.store.backend = args.backend

    data = build_data(config, seed=args.seed, days=args.days)
    handler = _make_handler(data)
    httpd = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"AiraCare dashboard on {url}  (backend={config.store.backend}, patient={config.patient.id})")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - interactive
        print("\nShutting down.")
    finally:
        httpd.server_close()
    return 0


__all__ = ["build_data", "main"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
