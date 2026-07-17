"""Foundry A2A server — the cloud endpoint the edge points at (``cloud.mode: foundry``).

A stdlib HTTP server that speaks the exact JSON-RPC 2.0 / A2A envelope the edge's
``A2AClient`` expects. It is a **drop-in replacement** for
``edge/airacare_edge/cloud/a2a_stub.py`` — same two methods, but backed by the
:class:`CareOrchestrator` (T1 considered assessment + async deliberate tier) instead of the edge's
in-process stub:

- ``airacare.report``       params ``{event}``                     -> ``CloudAssessment | null``
- ``airacare.fetch_policy`` params ``{patient_id, since_version}`` -> ``EdgePolicyUpdate | null``

Run standalone:

    python -m airacare_foundry.a2a_server --config config.yaml
    python -m airacare_foundry.a2a_server --port 8971
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from airacare_foundry.contracts import DailyLivingEvent
from airacare_foundry.orchestrator import CareOrchestrator, default_orchestrator

# Must match edge/airacare_foundry/cloud/a2a_client.py
REPORT_METHOD = "airacare.report"
FETCH_POLICY_METHOD = "airacare.fetch_policy"

# Env var holding the optional bearer token. When set, POST requests must carry
# ``Authorization: Bearer <token>``; when unset, the endpoint is open (local/demo).
TOKEN_ENV = "AIRACARE_A2A_TOKEN"


def _make_handler(
    orchestrator: CareOrchestrator, token: str | None, log: bool
) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            # Liveness/readiness probe — never authenticated so orchestrators can poll it.
            if self.path.rstrip("/") in ("/healthz", "/health"):
                self._send(200, {"status": "ok"})
            else:
                self._send(404, {"error": {"message": "not found"}})

        def do_POST(self) -> None:  # noqa: N802 (http.server API)
            if not self._authorized():
                self._log("POST", None, 401)
                self._send(401, {"jsonrpc": "2.0", "id": None, "error": {"message": "unauthorized"}})
                return
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            rpc_id = None
            method = None
            try:
                payload = json.loads(raw)
                rpc_id = payload.get("id")
                method = payload.get("method")
                params = payload.get("params", {})
                if method == REPORT_METHOD:
                    event = DailyLivingEvent.model_validate(params["event"])
                    assessment = orchestrator.report(event)
                    result = json.loads(assessment.model_dump_json()) if assessment else None
                elif method == FETCH_POLICY_METHOD:
                    update = orchestrator.fetch_policy(
                        params["patient_id"], params["since_version"]
                    )
                    result = json.loads(update.model_dump_json()) if update else None
                else:
                    raise ValueError(f"unknown method: {method}")
                self._send(200, {"jsonrpc": "2.0", "id": rpc_id, "result": result})
                self._log(method, rpc_id, 200)
            except Exception as exc:  # noqa: BLE001 (server boundary)
                self._send(400, {"jsonrpc": "2.0", "id": rpc_id, "error": {"message": str(exc)}})
                self._log(method, rpc_id, 400)

        def _authorized(self) -> bool:
            if not token:
                return True
            header = self.headers.get("Authorization", "")
            return header == f"Bearer {token}"

        def _send(self, code: int, obj: dict) -> None:
            data = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _log(self, method: str | None, rpc_id, code: int) -> None:
            if log:
                print(
                    f"[a2a] {self.command} {self.path} method={method} id={rpc_id} -> {code}",
                    file=sys.stderr,
                )

        def log_message(self, *args) -> None:  # silence the default per-request access log
            pass

    return _Handler


class FoundryA2AServer:
    """Threaded A2A server. Use as a context manager in tests, or ``serve_forever``."""

    def __init__(
        self,
        orchestrator: CareOrchestrator | None = None,
        host: str = "127.0.0.1",
        port: int = 8971,
        *,
        token: str | None = None,
        log: bool = False,
    ) -> None:
        self._orchestrator = orchestrator or default_orchestrator()
        # Token precedence: explicit arg > env. None/"" => open endpoint (local/demo).
        self._token = token if token is not None else os.environ.get(TOKEN_ENV) or None
        handler = _make_handler(self._orchestrator, self._token, log)
        self._server = ThreadingHTTPServer((host, port), handler)
        self.host, self.port = self._server.server_address
        self._thread: threading.Thread | None = None

    @property
    def endpoint(self) -> str:
        return f"http://{self.host}:{self.port}/a2a"

    @property
    def auth_required(self) -> bool:
        return bool(self._token)

    def start_background(self) -> "FoundryA2AServer":
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def serve_forever(self) -> None:
        self._server.serve_forever()

    def shutdown(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        # Drain any in-flight deliberate (T2) jobs so nothing is lost on shutdown.
        self._orchestrator.drain()

    def __enter__(self) -> "FoundryA2AServer":
        return self.start_background()

    def __exit__(self, *exc) -> None:
        self.shutdown()


def main() -> None:
    import argparse

    from airacare_foundry._console import ensure_utf8_stdout
    from airacare_foundry.config import FoundryConfig

    ensure_utf8_stdout()
    parser = argparse.ArgumentParser(description="AiraCare Foundry Care Orchestrator (A2A)")
    parser.add_argument("--config", default=None, help="path to config.yaml")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    if args.config:
        config = FoundryConfig.load(args.config)
        orchestrator = CareOrchestrator.from_config(config)
        host = args.host or config.server.host
        port = args.port if args.port is not None else config.server.port
    else:
        orchestrator = default_orchestrator()
        host = args.host or "127.0.0.1"
        port = args.port if args.port is not None else 8971

    server = FoundryA2AServer(orchestrator, host, port, log=True)
    auth = "bearer-token required" if server.auth_required else "open (no auth)"
    print(f"AiraCare Foundry orchestrator listening on {server.endpoint}  [{auth}]  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping…")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
