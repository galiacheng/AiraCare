"""Bearer-token wiring for mode: foundry.

The hosted Foundry agent requires an ``Authorization: Bearer <token>`` header. The token must
never be baked into config.yaml — the factory resolves it from the environment (either via a
``${VAR}`` reference in the config or the ``AIRACARE_A2A_TOKEN`` fallback), and the A2A client
attaches it to every request.
"""

from __future__ import annotations

import json

from airacare_edge.cloud import a2a_client as a2a_mod
from airacare_edge.cloud.a2a_client import A2AClient
from airacare_edge.cloud.factory import make_cloud_client
from airacare_edge.cloud.foundry_client import FoundryA2AClient
from airacare_edge.cloud.stub import LocalCloudStub
from airacare_edge.config import CloudConfig, EdgeConfig, PatientConfig


def _config(**cloud_kwargs) -> EdgeConfig:
    return EdgeConfig(
        patient=PatientConfig(id="p-001", name="Grandpa Zhang", disease_stage="moderate"),
        cloud=CloudConfig(**cloud_kwargs),
    )


def test_stub_mode_ignores_token():
    client = make_cloud_client(_config(mode="stub"))
    assert isinstance(client, LocalCloudStub)


def test_env_reference_token_resolved_from_environment(monkeypatch):
    monkeypatch.setenv("AIRACARE_A2A_TOKEN", "secret-xyz")
    client = make_cloud_client(
        _config(mode="foundry", a2a_endpoint="https://host/", a2a_token="${AIRACARE_A2A_TOKEN}")
    )
    assert isinstance(client, FoundryA2AClient)
    assert client._token == "secret-xyz"


def test_env_fallback_when_token_unset(monkeypatch):
    monkeypatch.setenv("AIRACARE_A2A_TOKEN", "from-env")
    client = make_cloud_client(_config(mode="foundry", a2a_endpoint="https://host/"))
    assert client._token == "from-env"


def test_literal_token_passthrough(monkeypatch):
    monkeypatch.delenv("AIRACARE_A2A_TOKEN", raising=False)
    client = make_cloud_client(
        _config(mode="foundry", a2a_endpoint="https://host/", a2a_token="literal-token")
    )
    assert client._token == "literal-token"


def test_no_token_available_is_none(monkeypatch):
    monkeypatch.delenv("AIRACARE_A2A_TOKEN", raising=False)
    client = make_cloud_client(_config(mode="a2a", a2a_endpoint="http://host/"))
    assert client._token is None


def test_client_attaches_authorization_header(monkeypatch):
    captured = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return json.dumps({"result": None}).encode()

    def _fake_urlopen(request, timeout=None):
        captured["headers"] = request.headers
        return _Resp()

    monkeypatch.setattr(a2a_mod.urllib.request, "urlopen", _fake_urlopen)
    A2AClient("https://host/", token="tok-123")._call("airacare.report", {})
    # urllib normalizes header names to Title-Case.
    assert captured["headers"].get("Authorization") == "Bearer tok-123"


def test_client_omits_header_without_token(monkeypatch):
    captured = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return json.dumps({"result": None}).encode()

    def _fake_urlopen(request, timeout=None):
        captured["headers"] = request.headers
        return _Resp()

    monkeypatch.setattr(a2a_mod.urllib.request, "urlopen", _fake_urlopen)
    A2AClient("https://host/")._call("airacare.report", {})
    assert "Authorization" not in captured["headers"]
