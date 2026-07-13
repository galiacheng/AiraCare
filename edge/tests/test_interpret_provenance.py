"""Tests for LocalVoiceService.interpret provenance (keyword vs LLM)."""

from __future__ import annotations

from airacare_edge.cloud.contracts import ReplyIntent
from airacare_edge.config import EdgeConfig, PatientConfig, VoiceConfig
from airacare_edge.voice.service import LocalVoiceService


class FakeLLM:
    def __init__(self, status: str | None) -> None:
        self._status = status

    def interpret(self, transcript: str) -> ReplyIntent | None:
        if self._status is None:
            return None
        return ReplyIntent(status=self._status, urgency=0.9, transcript=transcript)


def _service(status: str | None, use_llm: bool = True) -> LocalVoiceService:
    config = EdgeConfig(
        patient=PatientConfig(id="p", name="Grandpa Zhang"),
        voice=VoiceConfig(use_llm_for_ambiguous=use_llm),
    )
    service = LocalVoiceService(config)
    service._llm = FakeLLM(status)  # inject fake LLM (no Ollama)
    return service


def test_keyword_resolves_without_llm():
    service = _service(status="distress")  # LLM present but should not be used
    intent = service.interpret("I'm fine")
    assert intent.status == "ok"
    assert service.last_interpretation == {
        "keyword": "ok",
        "llm_used": False,
        "llm_result": None,
        "final": "ok",
    }


def test_unclear_upgraded_by_llm():
    service = _service(status="distress")
    intent = service.interpret("ummm the thing over there")
    assert intent.status == "distress"
    prov = service.last_interpretation
    assert prov["keyword"] == "unclear"
    assert prov["llm_used"] is True
    assert prov["llm_result"] == "distress"
    assert prov["final"] == "distress"


def test_unclear_kept_when_llm_returns_none():
    service = _service(status=None)  # LLM fails / unavailable
    intent = service.interpret("ummm the thing over there")
    assert intent.status == "unclear"
    prov = service.last_interpretation
    assert prov["llm_used"] is True
    assert prov["llm_result"] is None
    assert prov["final"] == "unclear"


def test_llm_disabled_stays_keyword():
    service = _service(status="distress", use_llm=False)
    intent = service.interpret("ummm the thing over there")
    assert intent.status == "unclear"
    assert service.last_interpretation["llm_used"] is False
