"""Factory that builds the right CloudGateway from config.

- ``stub``    -> in-process gateway (no network) — fastest for dev/tests.
- ``a2a``     -> bespoke JSON-RPC client to the local stub server (real HTTP, drop-in shape).
- ``foundry`` -> standard-A2A client to the real Foundry Hosted Agent (``message/send`` + task
  poll, Entra bearer). The bespoke ``foundry-a2a-server`` is no longer in the path.
"""

from __future__ import annotations

import os
import re

from airacare_edge.agent import CloudGateway
from airacare_edge.cloud.a2a_client import A2AClient
from airacare_edge.cloud.foundry_client import FoundryA2AClient
from airacare_edge.cloud.stub import LocalCloudStub
from airacare_edge.config import EdgeConfig

_ENV_REF = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


def _resolve_token(raw: str | None) -> str | None:
    """Resolve the bearer token, keeping secrets out of config.yaml.

    A ``${VAR}`` value is read from the environment; any other non-empty string is used
    verbatim. When unset, fall back to the ``AIRACARE_A2A_TOKEN`` env var (the same name the
    hosted agent reads), so the token can be injected without touching config at all.
    """
    if raw:
        match = _ENV_REF.match(raw.strip())
        if match:
            return os.environ.get(match.group(1)) or None
        return raw
    return os.environ.get("AIRACARE_A2A_TOKEN") or None


def make_cloud_client(config: EdgeConfig) -> CloudGateway:
    if config.cloud.mode == "stub":
        return LocalCloudStub()
    token = _resolve_token(config.cloud.a2a_token)
    if config.cloud.mode == "foundry":
        # Standard A2A to the real Foundry hosted agent (Entra bearer; falls back to azure-identity
        # when no token is injected). The endpoint is the agent's a2a protocol base URL.
        return FoundryA2AClient(config.cloud.a2a_endpoint, token=token)
    # "a2a" -> bespoke JSON-RPC client to the local stub server.
    return A2AClient(config.cloud.a2a_endpoint, token=token)
