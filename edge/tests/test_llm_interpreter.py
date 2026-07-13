"""OllamaInterpreter tests using a fake ``ollama`` module (no server needed)."""

from __future__ import annotations

import sys
import types

from airacare_edge.voice.llm import OllamaInterpreter


def _fake_ollama(content: str | None = None, raises: bool = False):
    module = types.ModuleType("ollama")

    def chat(**_kwargs):
        if raises:
            raise RuntimeError("ollama not running")
        return {"message": {"content": content}}

    module.chat = chat  # type: ignore[attr-defined]
    return module


def test_interpreter_parses_distress(monkeypatch):
    monkeypatch.setitem(sys.modules, "ollama", _fake_ollama('{"status":"distress","urgency":0.8}'))
    intent = OllamaInterpreter().interpret("I'm scared and I don't know where I am")
    assert intent is not None
    assert intent.status == "distress"
    assert 0.0 <= intent.urgency <= 1.0


def test_interpreter_parses_ok(monkeypatch):
    monkeypatch.setitem(sys.modules, "ollama", _fake_ollama('{"status":"ok","urgency":0.1}'))
    intent = OllamaInterpreter().interpret("no no I'm quite alright dear")
    assert intent is not None
    assert intent.status == "ok"


def test_interpreter_invalid_json_returns_none(monkeypatch):
    monkeypatch.setitem(sys.modules, "ollama", _fake_ollama("this is not json"))
    assert OllamaInterpreter().interpret("blah") is None


def test_interpreter_bad_status_returns_none(monkeypatch):
    monkeypatch.setitem(sys.modules, "ollama", _fake_ollama('{"status":"maybe"}'))
    assert OllamaInterpreter().interpret("blah") is None


def test_interpreter_error_returns_none(monkeypatch):
    monkeypatch.setitem(sys.modules, "ollama", _fake_ollama(raises=True))
    assert OllamaInterpreter().interpret("blah") is None
