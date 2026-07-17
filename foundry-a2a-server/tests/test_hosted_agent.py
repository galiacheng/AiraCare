"""Tests for the DEPLOYED Foundry Hosted Agent advisory narrator (offline; no network, no AAD).

Covers three layers:
- **Config**: ``hosted_agent_endpoint`` / ``hosted_agent_name`` parse and expand ``${ENV_VAR}``.
- **Wiring**: :func:`_build_narrator` selects the hosted-agent narrator (and it takes precedence
  over the in-process ``foundry_*`` model binding) only for the async executors.
- **Narrator**: :class:`HostedAgentNarrator` builds the right request, caches its token, and
  extracts the final message text from a Responses payload — all with fakes (no real HTTP/AAD).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from airacare_foundry.agents.hosted_agent import HostedAgentNarrator
from airacare_foundry.config import DeliberateConfig, FoundryConfig, PatientConfig
from airacare_foundry.contracts import CloudAssessment, DailyLivingEvent, utcnow
from airacare_foundry.orchestrator import _build_narrator

HOSTED_URL = (
    "https://acct.services.ai.azure.com/api/projects/proj/agents/"
    "airacare-care-orchestrator/endpoint/protocols/openai/responses?api-version=v1"
)


# -- Config resolvers ------------------------------------------------------------------------


def test_hosted_agent_config_resolves_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HA_TEST_ENDPOINT", HOSTED_URL)
    dc = DeliberateConfig(
        executor="thread",
        hosted_agent_endpoint="${HA_TEST_ENDPOINT}",
        hosted_agent_name="airacare-care-orchestrator",
    )
    assert dc.resolve_hosted_agent_endpoint() == HOSTED_URL
    assert dc.resolve_hosted_agent_name() == "airacare-care-orchestrator"  # plain value as-is
    assert dc.hosted_agent_token_scope == "https://ai.azure.com/.default"


def test_hosted_agent_config_unset_is_none() -> None:
    dc = DeliberateConfig()
    assert dc.resolve_hosted_agent_endpoint() is None
    assert dc.resolve_hosted_agent_name() is None


# -- Narrator wiring / precedence ------------------------------------------------------------


def _cfg(**deliberate) -> FoundryConfig:
    return FoundryConfig(
        patient=PatientConfig(id="p-001", name="Rose", disease_stage="severe"),
        deliberate=DeliberateConfig(**deliberate),
    )


def test_build_narrator_selects_hosted_agent_for_async_executors() -> None:
    # Hosted-agent endpoint set + async executor -> a callable narrator (no model binding needed).
    assert _build_narrator(_cfg(executor="thread", hosted_agent_endpoint=HOSTED_URL)) is not None
    assert _build_narrator(_cfg(executor="agents", hosted_agent_endpoint=HOSTED_URL)) is not None


def test_build_narrator_ignores_hosted_agent_for_inline_executor() -> None:
    # inline is synchronous — the advisory model call must never run on the report path.
    assert _build_narrator(_cfg(executor="inline", hosted_agent_endpoint=HOSTED_URL)) is None


def test_hosted_agent_takes_precedence_over_foundry_model(monkeypatch: pytest.MonkeyPatch) -> None:
    # When both are configured, the deployed hosted agent wins and build_workflow is never touched.
    def _boom(*_args, **_kwargs):  # pragma: no cover - must not be called
        raise AssertionError("in-process build_workflow must not be used when hosted agent is set")

    monkeypatch.setattr("airacare_foundry.agents.agent_framework.build_workflow", _boom)
    narrator = _build_narrator(
        _cfg(
            executor="agents",
            hosted_agent_endpoint=HOSTED_URL,
            hosted_agent_name="airacare-care-orchestrator",
            foundry_endpoint="https://acct.openai.azure.com/",
            foundry_deployment="gpt-5.4",
        )
    )
    assert narrator is not None


# -- HostedAgentNarrator behaviour (fake credential + fake HTTP) ------------------------------


class _FakeCredential:
    def __init__(self) -> None:
        self.calls = 0

    def get_token(self, scope: str):  # noqa: ANN001 - mimic azure.identity signature
        self.calls += 1
        return SimpleNamespace(token=f"tok-for-{scope}", expires_on=9_999_999_999)


def _extract() -> HostedAgentNarrator:
    return HostedAgentNarrator(HOSTED_URL, "airacare-care-orchestrator", credential=_FakeCredential())


def test_extract_text_prefers_output_text() -> None:
    assert _extract()._extract_text({"output_text": "  hello  "}) == "hello"


def test_extract_text_concatenates_message_items_and_skips_tools() -> None:
    payload = {
        "output": [
            {"type": "function_call", "name": "search_care_guidelines"},
            {"type": "function_call_output"},
            {"type": "message", "content": [{"type": "output_text", "text": "Line one."}]},
            {"type": "message", "content": [{"type": "output_text", "text": "Line two."}]},
        ]
    }
    assert _extract()._extract_text(payload) == "Line one.\nLine two."


def test_narrate_posts_case_and_returns_briefing(monkeypatch: pytest.MonkeyPatch) -> None:
    cred = _FakeCredential()
    narrator = HostedAgentNarrator(HOSTED_URL, "airacare-care-orchestrator", credential=cred)
    captured: dict[str, object] = {}

    class _FakeResp:
        def __init__(self, body: bytes) -> None:
            self._body = body

        def read(self) -> bytes:
            return self._body

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, *_exc):  # noqa: ANN002
            return False

    def _fake_urlopen(request, timeout=None):  # noqa: ANN001
        captured["url"] = request.full_url
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _FakeResp(json.dumps({"output_text": "Family recap: he is safe."}).encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    out = narrator.narrate("CASE FILE: ...")
    assert out == "Family recap: he is safe."
    assert captured["url"] == HOSTED_URL
    assert captured["auth"] == "Bearer tok-for-https://ai.azure.com/.default"
    assert captured["body"] == {"model": "airacare-care-orchestrator", "input": "CASE FILE: ..."}

    # Second call reuses the cached (non-expired) token — no extra get_token.
    narrator.narrate("CASE FILE: again")
    assert cred.calls == 1


def test_narrator_records_into_tier_via_case_file(monkeypatch: pytest.MonkeyPatch) -> None:
    # End-to-end wiring: _build_narrator -> hosted narrator -> DeliberateTier.narrative_log.
    from airacare_foundry.agents.deliberate import DeliberateTier

    def _fake_urlopen(request, timeout=None):  # noqa: ANN001
        class _R:
            def read(self):
                return json.dumps({"output_text": "briefing ok"}).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

        return _R()

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    monkeypatch.setattr(
        "airacare_foundry.agents.hosted_agent.HostedAgentNarrator._bearer",
        lambda self: "tok",
    )
    narrator = _build_narrator(
        _cfg(executor="thread", hosted_agent_endpoint=HOSTED_URL, hosted_agent_name="a")
    )
    tier = DeliberateTier(enabled=True, narrator=narrator)
    tier.schedule(
        DailyLivingEvent(
            type="wander",
            confidence=0.9,
            timestamp=utcnow(),
            patient_id="p-001",
            features=[],
            baseline_deviation=0.95,
            edge_assessed_level="L3",
            edge_action_taken="escalated",
            context={"time_of_day": "night"},
        ),
        None,
        CloudAssessment(considered_level="L3", reason="considered L3 for wander"),
    )
    tier.join()
    assert tier.narrative_log == ["briefing ok"]
