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
    sqlite_path: str = ":memory:"  # ":memory:" or a file path to persist


class PatientConfig(BaseModel):
    id: str
    name: str
    disease_stage: Literal["mild", "moderate", "severe"] = "moderate"


class DeliberateConfig(BaseModel):
    enabled: bool = False  # async multi-agent tier is stubbed in this scaffold


class FoundryConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    store: StoreConfig = Field(default_factory=StoreConfig)
    patient: PatientConfig
    deliberate: DeliberateConfig = Field(default_factory=DeliberateConfig)

    @classmethod
    def load(cls, path: str | Path) -> "FoundryConfig":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(data)
