"""Factory that builds the right CloudGateway from config.

- ``stub``    -> in-process gateway (no network) — fastest for dev/tests.
- ``a2a``     -> A2A client to the local stub server (real HTTP, drop-in shape).
- ``foundry`` -> A2A client to the real Foundry Hosted Agent (same client, real endpoint).
"""

from __future__ import annotations

from airacare_edge.agent import CloudGateway
from airacare_edge.cloud.a2a_client import A2AClient
from airacare_edge.cloud.stub import LocalCloudStub
from airacare_edge.config import EdgeConfig


def make_cloud_client(config: EdgeConfig) -> CloudGateway:
    if config.cloud.mode == "stub":
        return LocalCloudStub()
    # "a2a" (local stub server) and "foundry" (real hosted agent) both speak A2A/HTTP.
    return A2AClient(config.cloud.a2a_endpoint)
