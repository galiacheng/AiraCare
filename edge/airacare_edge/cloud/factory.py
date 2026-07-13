"""Factory that builds the right CloudClient from config.

- ``stub``    -> in-process grading (no network) — fastest for dev/tests.
- ``a2a``     -> A2A client to the local stub server (real HTTP, drop-in shape).
- ``foundry`` -> A2A client to the real Foundry Hosted Agent (same client, real endpoint).
"""

from __future__ import annotations

from airacare_edge.agent import CloudClient
from airacare_edge.cloud.a2a_client import A2AClient
from airacare_edge.cloud.stub import LocalStubCloudClient
from airacare_edge.config import EdgeConfig


def make_cloud_client(config: EdgeConfig) -> CloudClient:
    if config.cloud.mode == "stub":
        return LocalStubCloudClient()
    # "a2a" (local stub server) and "foundry" (real hosted agent) both speak A2A/HTTP.
    return A2AClient(config.cloud.a2a_endpoint)
