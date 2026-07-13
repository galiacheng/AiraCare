"""Local A2A stub server — stands in for the Foundry Hosted Agent.

A tiny stdlib HTTP server that speaks the same JSON-RPC 2.0 / A2A-shaped envelope the
real Foundry agent will. It grades an incoming DailyLivingEvent with the in-process
LocalGradingEngine and returns a CloudDecision. Swapping to the real Foundry Hosted
Agent means pointing the client at Foundry instead of this server — no edge changes.

Run standalone:

    python -m airacare_edge.cloud.a2a_stub --port 8971
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from airacare_edge.cloud.a2a_client import GRADE_METHOD
from airacare_edge.cloud.contracts import DailyLivingEvent
from airacare_edge.cloud.stub import LocalGradingEngine


class _Handler(BaseHTTPRequestHandler):
    engine = LocalGradingEngine()

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw)
            if payload.get("method") != GRADE_METHOD:
                raise ValueError(f"unknown method: {payload.get('method')}")
            event = DailyLivingEvent.model_validate(payload["params"]["event"])
            decision = self.engine.grade(event)
            self._send(
                200,
                {
                    "jsonrpc": "2.0",
                    "id": payload.get("id"),
                    "result": json.loads(decision.model_dump_json()),
                },
            )
        except Exception as exc:  # noqa: BLE001 (stub boundary)
            self._send(400, {"jsonrpc": "2.0", "id": None, "error": {"message": str(exc)}})

    def _send(self, code: int, obj: dict) -> None:
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:  # keep the console quiet
        pass


class A2AStubServer:
    """Threaded A2A stub. Use as a context manager in tests, or ``serve_forever``."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8971) -> None:
        self._server = ThreadingHTTPServer((host, port), _Handler)
        self.host, self.port = self._server.server_address
        self._thread: threading.Thread | None = None

    @property
    def endpoint(self) -> str:
        return f"http://{self.host}:{self.port}/a2a"

    def start_background(self) -> "A2AStubServer":
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def serve_forever(self) -> None:
        self._server.serve_forever()

    def shutdown(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self) -> "A2AStubServer":
        return self.start_background()

    def __exit__(self, *exc) -> None:
        self.shutdown()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="AiraCare A2A stub (Foundry stand-in)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8971)
    args = parser.parse_args()

    server = A2AStubServer(args.host, args.port)
    print(f"AiraCare A2A stub listening on {server.endpoint}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping…")


if __name__ == "__main__":
    main()
