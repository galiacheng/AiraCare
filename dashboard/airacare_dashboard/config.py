"""Typed configuration for the care dashboard, loaded from a small YAML file.

Only the two sections the dashboard actually needs are modelled: ``patient`` (which patient the
page defaults to) and ``store`` (where filed events live — local SQLite or Azure Cosmos). Secrets
and endpoints may be inlined for local convenience or, preferably, injected from the environment
via a whole-string ``${ENV_VAR}`` reference so nothing sensitive lives in the YAML.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


def _expand_env(raw: str | None) -> str | None:
    """Expand a whole-string ``${ENV_VAR}`` reference from the process environment.

    A plain (non-``${...}``) value is returned unchanged, so local/emulator configs keep working
    while container/live deploys inject secrets/endpoints via the environment.
    """
    if raw and raw.startswith("${") and raw.endswith("}"):
        return os.environ.get(raw[2:-1])
    return raw


class StoreConfig(BaseModel):
    """Where the dashboard reads filed events from (must match the hosted agent's writer)."""

    backend: Literal["local", "cosmos"] = "local"
    sqlite_path: str = ":memory:"  # ":memory:" or a file path (local backend, offline dry-run)
    # Cosmos backend (the live demo). ``credential`` may be inlined or injected from the
    # environment; ``database`` names the Cosmos DB (partition key = /patient_id everywhere).
    cosmos_endpoint: str | None = None
    cosmos_credential: str | None = None
    cosmos_database: str = "airacare"
    # Auth mode: "key" uses ``cosmos_credential`` (account key); "aad" ignores the key and uses
    # azure.identity.DefaultAzureCredential (Managed Identity in prod, ``az login`` locally).
    cosmos_auth: Literal["key", "aad"] = "key"
    # TLS verification. True for real accounts; set False only for the local emulator's
    # self-signed cert (localhost). NEVER disable against a real endpoint.
    cosmos_tls_verify: bool = True

    def resolve_credential(self) -> str | None:
        """Return the account key, expanding a ``${ENV_VAR}`` reference from the environment."""
        return _expand_env(self.cosmos_credential)

    def resolve_endpoint(self) -> str | None:
        """Return the Cosmos endpoint, expanding a ``${ENV_VAR}`` reference (container deploys)."""
        return _expand_env(self.cosmos_endpoint)

    def resolve_database(self) -> str:
        """Return the Cosmos database name, expanding a ``${ENV_VAR}`` reference if present."""
        return _expand_env(self.cosmos_database) or "airacare"


class PatientConfig(BaseModel):
    id: str
    name: str
    disease_stage: Literal["mild", "moderate", "severe"] = "moderate"


class DashboardConfig(BaseModel):
    """Top-level dashboard config: the default patient + the event store to read."""

    store: StoreConfig = Field(default_factory=StoreConfig)
    patient: PatientConfig

    @classmethod
    def load(cls, path: str | Path) -> "DashboardConfig":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(data)


__all__ = ["DashboardConfig", "StoreConfig", "PatientConfig"]
