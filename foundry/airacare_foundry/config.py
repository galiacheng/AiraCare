"""Typed configuration for the Foundry Care Orchestrator, loaded from ``config.yaml``."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


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


class PatientConfig(BaseModel):
    id: str
    name: str
    disease_stage: Literal["mild", "moderate", "severe"] = "moderate"


class DeliberateConfig(BaseModel):
    enabled: bool = False  # async multi-agent tier is stubbed in this scaffold


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
