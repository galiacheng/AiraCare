"""A2A client — reports a DailyLivingEvent to a remote agent and fetches policy.

Uses a minimal JSON-RPC 2.0 envelope over HTTP (the shape the A2A / Agent2Agent protocol
uses). The same client talks to our local stub server (``mode: a2a``) and, by changing
only the endpoint/credentials, to the real Foundry Hosted Agent (``mode: foundry``).
Connection failures return ``None`` — the edge has already acted, so the report is simply
queued for store-and-forward; connectivity loss is never fatal.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from airacare_edge.cloud.contracts import CloudAssessment, DailyLivingEvent, EdgePolicyUpdate

REPORT_METHOD = "airacare.report"
FETCH_POLICY_METHOD = "airacare.fetch_policy"


class A2AClient:
    def __init__(self, endpoint: str, timeout: float = 5.0, token: str | None = None) -> None:
        self._endpoint = endpoint
        self._timeout = timeout
        self._token = token

    def _call(self, method: str, params: dict) -> dict | None:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        request = urllib.request.Request(
            self._endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            return None  # offline / unreachable
        return body.get("result")

    def report(self, event: DailyLivingEvent) -> CloudAssessment | None:
        result = self._call(REPORT_METHOD, {"event": json.loads(event.model_dump_json())})
        if result is None:
            return None
        return CloudAssessment.model_validate(result)

    def fetch_policy(self, patient_id: str, since_version: int) -> EdgePolicyUpdate | None:
        result = self._call(
            FETCH_POLICY_METHOD,
            {"patient_id": patient_id, "since_version": since_version},
        )
        if not result:  # None or empty {} -> no new policy
            return None
        return EdgePolicyUpdate.model_validate(result)
