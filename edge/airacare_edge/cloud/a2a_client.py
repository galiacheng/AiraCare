"""A2A client — submits a DailyLivingEvent to a remote agent and parses the decision.

Uses a minimal JSON-RPC 2.0 envelope over HTTP (the shape the A2A / Agent2Agent
protocol uses). The same client talks to our local stub server (``mode: a2a``) and, by
changing only the endpoint/credentials, to the real Foundry Hosted Agent
(``mode: foundry``). Connection failures return ``None`` so the edge falls back to its
offline behavior — connectivity loss is never fatal.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from airacare_edge.cloud.contracts import CloudDecision, DailyLivingEvent

GRADE_METHOD = "airacare.grade"


class A2AClient:
    def __init__(self, endpoint: str, timeout: float = 5.0) -> None:
        self._endpoint = endpoint
        self._timeout = timeout

    def submit(self, event: DailyLivingEvent) -> CloudDecision | None:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": GRADE_METHOD,
            "params": {"event": json.loads(event.model_dump_json())},
        }
        request = urllib.request.Request(
            self._endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            return None  # offline / unreachable -> edge falls back locally

        result = body.get("result")
        if result is None:
            return None
        return CloudDecision.model_validate(result)
