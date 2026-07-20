"""Standard-A2A client to the Foundry Hosted Agent (``mode: foundry``).

Speaks the standard **A2A / Agent2Agent** JSON-RPC 2.0 protocol (``message/send`` +
``tasks/get``) directly to the deployed Foundry hosted agent — so the bespoke
``foundry-a2a-server`` is no longer in the path. The edge forwards a privacy-scrubbed
:class:`DailyLivingEvent` as a delimited ``DAILY EVENT RECORD (JSON)`` text block; the hosted
agent's deterministic middleware files it to Cosmos and appends a ``CONSIDERED ASSESSMENT
(JSON)`` block, which this client locates and decodes back into a :class:`CloudAssessment`.

Two Foundry A2A facts shape the client:

* **No streaming** (the preview A2A endpoint has ``capabilities.streaming = false``): a
  ``message/send`` returns a *task* that starts in ``working`` and must be polled with
  ``tasks/get`` until it reaches a terminal state. The considered block arrives as one of the
  completed task's ``artifacts`` (text parts).
* **Entra auth**: the caller needs an AAD bearer token for the ``https://ai.azure.com`` resource
  (role: *Foundry Agent Consumer*+). A token may be injected explicitly (config/env); otherwise
  the client lazily acquires one via ``azure-identity`` if that optional package is installed.

Like :class:`~airacare_edge.cloud.a2a_client.A2AClient`, every failure path (offline, auth
missing, timeout, malformed reply) returns ``None`` — the edge has already acted locally, so the
report is simply queued for store-and-forward. Connectivity loss is never fatal.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid

from airacare_edge.cloud.contracts import CloudAssessment, DailyLivingEvent, EdgePolicyUpdate

DAILY_EVENT_MARKER = "DAILY EVENT RECORD (JSON)"
ASSESSMENT_MARKER = "CONSIDERED ASSESSMENT (JSON)"
AI_SCOPE = "https://ai.azure.com/.default"

# The advisory prompt that accompanies the forwarded record. The model narrates a warm recap; the
# considered level is decided deterministically by the hosted agent's middleware, never the model.
_FORWARD_PROMPT = (
    "A privacy-scrubbed daily-living event was forwarded from the edge. "
    "Please file it and give the family a brief, warm recap."
)

# Task states that mean "keep polling"; everything else is terminal (completed/failed/canceled/…).
_NON_TERMINAL_STATES = {"submitted", "working", None}


def build_daily_event_message(event: DailyLivingEvent) -> str:
    """Return the caregiver-turn text carrying the forwarded event as a DAILY EVENT RECORD block.

    The record is wrapped as ``{"event": {...}}`` — the exact shape the hosted agent's
    ``_extract_daily_event_record`` decodes — and serialized via ``model_dump_json`` so the
    timestamp and every field round-trip losslessly.
    """
    record = {"event": json.loads(event.model_dump_json())}
    return f"{_FORWARD_PROMPT}\n{DAILY_EVENT_MARKER}\n{json.dumps(record)}"


def parse_assessment_block(text: str) -> CloudAssessment | None:
    """Extract the considered :class:`CloudAssessment` from a reply's text, or ``None``.

    Mirrors the hosted agent's ``render.parse_assessment_block``: locate the marker, decode the
    JSON object that immediately follows it, and validate it. Never raises — a plain narration
    with no block (or a malformed one) simply yields ``None``.
    """
    marker = text.find(ASSESSMENT_MARKER)
    if marker == -1:
        return None
    brace = text.find("{", marker)
    if brace == -1:
        return None
    try:
        obj, _end = json.JSONDecoder().raw_decode(text, brace)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or "considered_level" not in obj:
        return None
    try:
        return CloudAssessment.model_validate(obj)
    except ValueError:
        return None


class FoundryA2AClient:
    """CloudGateway that speaks standard A2A to the Foundry hosted agent.

    ``report`` forwards the event and returns the deterministic considered assessment; ``fetch_policy``
    is a no-op (the standard-A2A topology retired the control-plane policy channel — the hosted agent
    always reports ``policy_version = 1``, so the edge never asks for an update).
    """

    def __init__(
        self,
        endpoint: str,
        token: str | None = None,
        timeout: float = 30.0,
        poll_interval: float = 3.0,
        poll_timeout: float = 60.0,
        credential: object | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._token = token
        self._timeout = timeout
        self._poll_interval = poll_interval
        self._poll_timeout = poll_timeout
        self._credential = credential

    # --- auth ----------------------------------------------------------------
    def _bearer(self) -> str | None:
        """Return the AAD bearer token: an injected one, else lazily via azure-identity, else None."""
        if self._token:
            return self._token
        try:
            if self._credential is None:
                from azure.identity import DefaultAzureCredential  # optional dep, lazy import

                self._credential = DefaultAzureCredential()
            return self._credential.get_token(AI_SCOPE).token  # azure-identity caches internally
        except Exception:  # noqa: BLE001 — no creds available -> treat as offline (report queues)
            return None

    # --- transport -----------------------------------------------------------
    def _rpc(self, method: str, params: dict) -> dict | None:
        """POST a JSON-RPC 2.0 request; return the ``result`` object, or ``None`` on any failure."""
        headers = {"Content-Type": "application/json"}
        bearer = self._bearer()
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        payload = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method, "params": params}
        request = urllib.request.Request(
            self._endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, ValueError):
            return None  # offline / unreachable / malformed
        if not isinstance(body, dict) or body.get("error"):
            return None
        result = body.get("result")
        return result if isinstance(result, dict) else None

    # --- gateway API ---------------------------------------------------------
    def report(self, event: DailyLivingEvent) -> CloudAssessment | None:
        params = {"message": self._message_params(event)}
        result = self._rpc("message/send", params)
        if result is None:
            return None
        text = self._await_text(result)
        if not text:
            return None
        assessment = parse_assessment_block(text)
        if assessment is None:
            return None
        # Preserve the hosted model's narrative recap (the value the parsed block alone drops) so the
        # edge/CLI can surface it. It is everything the agent said *before* the appended block.
        briefing = self._briefing_text(text)
        return assessment.model_copy(update={"briefing": briefing}) if briefing else assessment

    def fetch_policy(self, patient_id: str, since_version: int) -> EdgePolicyUpdate | None:
        # Standard-A2A topology has no policy channel; the hosted agent never bumps policy_version.
        return None

    # --- helpers -------------------------------------------------------------
    @staticmethod
    def _briefing_text(text: str) -> str:
        """The hosted model's narrative recap: everything before the appended assessment block.

        The middleware appends the ``CONSIDERED ASSESSMENT (JSON)`` block after the model's warm
        family recap, so the text ahead of that marker is the grounded briefing (with its citations).
        """
        return text.split(ASSESSMENT_MARKER, 1)[0].strip()

    @staticmethod
    def _message_params(event: DailyLivingEvent) -> dict:
        return {
            "kind": "message",
            "messageId": str(uuid.uuid4()),
            "role": "user",
            "parts": [{"kind": "text", "text": build_daily_event_message(event)}],
        }

    def _await_text(self, result: dict) -> str:
        """Resolve a ``message/send`` result to its full text, polling ``tasks/get`` for a task."""
        if result.get("kind") == "message":  # synchronous reply (no task)
            return self._collect_parts(result.get("parts"))
        task_id = result.get("id")
        state = (result.get("status") or {}).get("state")
        deadline = time.monotonic() + self._poll_timeout
        misses = 0
        while task_id and state in _NON_TERMINAL_STATES and time.monotonic() < deadline:
            time.sleep(self._poll_interval)
            polled = self._rpc("tasks/get", {"id": task_id})
            if polled is None:
                # A single transient blip must not abort a report that is still in flight;
                # retry a few times before giving up (the edge already acted regardless).
                misses += 1
                if misses >= 3:
                    break
                continue
            misses = 0
            result = polled
            state = (result.get("status") or {}).get("state")
        return self._collect_task_text(result)

    def _collect_task_text(self, result: dict) -> str:
        chunks = [self._collect_parts(((result.get("status") or {}).get("message") or {}).get("parts"))]
        for artifact in result.get("artifacts") or []:
            chunks.append(self._collect_parts(artifact.get("parts")))
        for message in result.get("history") or []:
            chunks.append(self._collect_parts(message.get("parts")))
        return "\n".join(chunk for chunk in chunks if chunk)

    @staticmethod
    def _collect_parts(parts: object) -> str:
        if not isinstance(parts, list):
            return ""
        texts = [
            part["text"]
            for part in parts
            if isinstance(part, dict) and part.get("kind") == "text" and part.get("text")
        ]
        return "\n".join(texts)
