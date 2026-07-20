"""Typed configuration for the edge agent, loaded from ``config.yaml``."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class PatientConfig(BaseModel):
    id: str
    name: str
    disease_stage: Literal["mild", "moderate", "severe"] = "moderate"


class QuietHours(BaseModel):
    start: str = "22:00"  # HH:MM
    end: str = "07:00"  # HH:MM


class Thresholds(BaseModel):
    wander_confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    no_response_seconds: float = Field(default=8.0, gt=0.0)
    correlation_window_seconds: float = Field(default=120.0, gt=0.0)


class VoiceConfig(BaseModel):
    input: Literal["mic", "file"] = "file"
    asr_model: str = "small"
    tts_engine: Literal["sapi", "piper"] = "sapi"
    tts_voice: str = "en_US-medium"
    llm_model: str = "phi3.5"
    use_llm_for_ambiguous: bool = True
    max_clarify_retries: int = 1  # re-ask once on 'unclear', then escalate
    sample_rate: int = 16000
    silence_seconds: float = 1.2  # trailing silence that ends an utterance
    energy_threshold: float = 0.02  # RMS threshold for the energy VAD
    # Edge-owned prompts (personalized via EdgePolicyUpdate). confirm supports {name}.
    confirm_prompt: str = "{name}, are you okay?"
    reassure_prompt: str = "It's late. Let's head back to bed — I'll leave a soft light on."
    clarify_prompt: str = "I didn't catch that. Are you okay?"
    # Read the heard reply back aloud (demo transparency). echo_prompt supports {reply}.
    echo_reply: bool = False
    echo_prompt: str = "I heard you say: {reply}"


class CloudConfig(BaseModel):
    mode: Literal["stub", "a2a", "foundry"] = "stub"
    a2a_endpoint: str = "http://localhost:8971/a2a"
    a2a_token: str | None = None  # bearer token; use "${AIRACARE_A2A_TOKEN}" to read from env
    offline_queue_dir: str = ".airacare_queue"  # local store-and-forward directory
    offline_ttl_seconds: float = 3600.0  # drop queued events older than this (default 1h)


class EdgeConfig(BaseModel):
    patient: PatientConfig
    quiet_hours: QuietHours = Field(default_factory=QuietHours)
    thresholds: Thresholds = Field(default_factory=Thresholds)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    cloud: CloudConfig = Field(default_factory=CloudConfig)

    @classmethod
    def load(cls, path: str | Path) -> "EdgeConfig":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(data)
