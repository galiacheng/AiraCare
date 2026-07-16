"""Factory that builds the right CloudGateway from config.

- ``stub``    -> in-process gateway (no network) — fastest for dev/tests.
- ``a2a``     -> A2A client to the local stub server (real HTTP, drop-in shape).
- ``foundry`` -> A2A client to the real Foundry Hosted Agent (same client, real endpoint).
"""

from __future__ import annotations

import os
import re

from airacare_edge.agent import CloudGateway
from airacare_edge.cloud.a2a_client import A2AClient
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
    # "a2a" (local stub server) and "foundry" (real hosted agent) both speak A2A/HTTP.
    return A2AClient(config.cloud.a2a_endpoint, token=_resolve_token(config.cloud.a2a_token))
