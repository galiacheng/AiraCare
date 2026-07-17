"""Typed configuration for the Foundry Care Orchestrator, loaded from ``config.yaml``."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


def _expand_env(raw: str | None) -> str | None:
    """Expand a whole-string ``${ENV_VAR}`` reference from the process environment.

    A plain (non-``${...}``) value is returned unchanged, so local/emulator configs keep working
    while container deploys inject secrets/endpoints via the environment.
    """
    if raw and raw.startswith("${") and raw.endswith("}"):
        return os.environ.get(raw[2:-1])
    return raw


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8971  # matches the edge's default a2a_endpoint


class StoreConfig(BaseModel):
    backend: Literal["local", "cosmos"] = "local"
    sqlite_path: str = ":memory:"  # ":memory:" or a file path to persist (local backend)
    # Cosmos backend (production). ``credential`` may be inlined or, preferably, injected from
    # the environment by the caller; ``database`` names the Cosmos DB (containers are created
    # on demand, partition key = /patient_id).
    cosmos_endpoint: str | None = None
    cosmos_credential: str | None = None
    cosmos_database: str = "airacare"
    # Auth mode: "key" uses ``cosmos_credential`` (account key); "aad" ignores the key and uses
    # azure.identity.DefaultAzureCredential (Managed Identity in prod, ``az login`` locally).
    cosmos_auth: Literal["key", "aad"] = "key"
    # TLS verification. True for real accounts; set False for the local emulator's self-signed
    # cert (localhost only). NEVER disable against a real endpoint.
    cosmos_tls_verify: bool = True

    def resolve_credential(self) -> str | None:
        """Return the account key, expanding a ``${ENV_VAR}`` reference from the environment.

        Keeps secrets out of ``config.yaml``: set ``cosmos_credential: ${AIRACARE_COSMOS_KEY}``
        (or any var name) and the real key is read from the process environment at load time.
        A plain (non-``${...}``) value is returned as-is for local/emulator convenience.
        """
        return _expand_env(self.cosmos_credential)

    def resolve_endpoint(self) -> str | None:
        """Return the Cosmos endpoint, expanding a ``${ENV_VAR}`` reference (container deploys).

        Lets a baked-in ``config.*.yaml`` stay environment-agnostic: set
        ``cosmos_endpoint: ${AIRACARE_COSMOS_ENDPOINT}`` and the hosting platform (e.g. Azure
        Container Apps) injects the real endpoint. A plain value is returned as-is.
        """
        return _expand_env(self.cosmos_endpoint)

    def resolve_database(self) -> str:
        """Return the Cosmos database name, expanding a ``${ENV_VAR}`` reference if present."""
        return _expand_env(self.cosmos_database) or "airacare"


class PatientConfig(BaseModel):
    id: str
    name: str
    disease_stage: Literal["mild", "moderate", "severe"] = "moderate"


class DeliberateConfig(BaseModel):
    enabled: bool = False  # async multi-agent tier is stubbed in this scaffold
    # How the deliberate (T2) jobs run relative to the report call:
    #   "inline"  — run in-thread (deterministic; default for tests/demo/CI)
    #   "thread"  — run on a background worker so report() returns immediately (hosted server)
    #   "agents"  — run on the Microsoft Agent Framework runtime ([agents] extra; FH3)
    executor: Literal["inline", "thread", "agents"] = "inline"
    # Foundry model binding for the "agents" executor (FH6). When both endpoint and deployment
    # resolve, the six Connected Agents are bound to this Azure AI Foundry / Azure OpenAI model
    # (AAD auth via Managed Identity / az login — never a key) and the deliberate tier composes an
    # advisory caregiver narrative. The model is narrative-only: it never sets the considered level
    # or drives escalation (the deterministic Python agents remain authoritative). Left unset ->
    # the "agents" executor still runs the deterministic T2, but produces no model narrative.
    # Values may be a plain string or a ``${ENV_VAR}`` reference (container deploys inject them).
    foundry_endpoint: str | None = None  # e.g. ${AIRACARE_FOUNDRY_ENDPOINT}
    foundry_deployment: str | None = None  # e.g. ${AIRACARE_FOUNDRY_DEPLOYMENT}
    # OpenAIChatClient talks the Azure OpenAI Responses API, which requires "preview" here.
    foundry_api_version: str = "preview"

    def resolve_foundry_endpoint(self) -> str | None:
        """Return the Foundry model endpoint, expanding a ``${ENV_VAR}`` reference if present."""
        return _expand_env(self.foundry_endpoint)

    def resolve_foundry_deployment(self) -> str | None:
        """Return the Foundry model/deployment name, expanding a ``${ENV_VAR}`` reference."""
        return _expand_env(self.foundry_deployment)


class KnowledgeConfig(BaseModel):
    # "local" = dependency-free in-memory guideline index (offline demo/tests);
    # "azure" = Azure AI Search vector RAG (install the [search] extra; placeholder here).
    backend: Literal["local", "azure"] = "local"


class FoundryConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    store: StoreConfig = Field(default_factory=StoreConfig)
    patient: PatientConfig
    deliberate: DeliberateConfig = Field(default_factory=DeliberateConfig)
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)
    # Cloud-owned escalation contact directory: channel -> target (e.g. phone/handle).
    contacts: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "FoundryConfig":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(data)
