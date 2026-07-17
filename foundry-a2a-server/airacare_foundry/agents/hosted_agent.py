"""Advisory narrator backed by a DEPLOYED Azure AI Foundry **Hosted Agent** (Responses protocol).

Unlike the in-process MAF workflow (:mod:`airacare_foundry.agents.agent_framework`), which binds
the six specialists to a shared model *inside this orchestrator process*, this narrator delegates
the entire advisory briefing to a **separately deployed** Foundry Hosted Agent — the graduated
``airacare-care-orchestrator`` that speaks the OpenAI **Responses** protocol and grounds its
answers in Foundry IQ knowledge.

It POSTs the fixed, privacy-scrubbed CASE FILE (see
:func:`airacare_foundry.agents.agent_framework.case_file`) to the agent's Responses endpoint and
returns the final assistant message text. Auth is AAD via ``DefaultAzureCredential`` (Managed
Identity in production, ``az login`` locally — never an API key). The token is cached and refreshed
shortly before expiry.

**Advisory only.** The hosted agent restates the considered level and never sets it or drives
escalation — the deterministic edge/cloud Python agents remain the sole authority. The call runs
strictly in the asynchronous deliberate tier (T2), off the edge safety path.
"""
from __future__ import annotations

import json
import time
import urllib.request
from typing import Any

_DEFAULT_TOKEN_SCOPE = "https://ai.azure.com/.default"
_TOKEN_REFRESH_SKEW = 120.0  # refresh a bit before the token actually expires


class HostedAgentNarrator:
    """Calls a deployed Foundry Hosted Agent's Responses endpoint to compose an advisory briefing.

    Parameters
    ----------
    endpoint:
        The agent's OpenAI Responses URL (``.../endpoint/protocols/openai/responses?api-version=v1``).
    name:
        The deployed agent name, sent as the Responses ``model`` field. Defaults to ``"agent"``.
    token_scope:
        AAD token audience for the data-plane call (defaults to ``https://ai.azure.com/.default``).
    timeout:
        Per-call HTTP timeout in seconds.
    credential:
        Optional pre-built AAD credential (anything exposing ``get_token(scope)``). When omitted,
        :class:`azure.identity.DefaultAzureCredential` is created lazily on first use so importing
        this module never requires azure-identity to be installed.
    """

    def __init__(
        self,
        endpoint: str,
        name: str | None = None,
        *,
        token_scope: str = _DEFAULT_TOKEN_SCOPE,
        timeout: float = 120.0,
        credential: Any | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._name = name or "agent"
        self._token_scope = token_scope
        self._timeout = timeout
        self._credential = credential
        self._token: str | None = None
        self._token_exp: float = 0.0

    def _bearer(self) -> str:
        now = time.time()
        if self._token is None or now >= self._token_exp - _TOKEN_REFRESH_SKEW:
            if self._credential is None:
                from azure.identity import DefaultAzureCredential

                self._credential = DefaultAzureCredential()
            token = self._credential.get_token(self._token_scope)
            self._token = token.token
            self._token_exp = float(token.expires_on)
        return self._token

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> str:
        """Pull the final assistant message text out of a Responses run payload.

        Prefers the convenience ``output_text`` field when present, otherwise concatenates the text
        chunks of every ``message`` item in ``output`` (skipping tool ``function_call`` items).
        """
        txt = payload.get("output_text")
        if isinstance(txt, str) and txt.strip():
            return txt.strip()
        parts: list[str] = []
        for item in payload.get("output", []) or []:
            if item.get("type") != "message":
                continue
            for chunk in item.get("content", []) or []:
                chunk_text = chunk.get("text")
                if isinstance(chunk_text, str) and chunk_text:
                    parts.append(chunk_text)
        return "\n".join(parts).strip()

    def narrate(self, case: str) -> str:
        """Run the deployed agent over ``case`` (a case-file string) and return its briefing text."""
        body = json.dumps({"model": self._name, "input": case}).encode("utf-8")
        request = urllib.request.Request(  # noqa: S310 — fixed Azure Foundry host
            self._endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._bearer()}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
        return self._extract_text(payload)
