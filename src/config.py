"""Configuration loader for PiGlot."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class AudioConfig(BaseModel):
    input_device: str = "default"
    output_device: str = "default"
    sample_rate: int = 16000
    silence_threshold: int = 500
    silence_duration: float = 1.5
    max_record_seconds: int = 30


class STTConfig(BaseModel):
    engine: Literal["whisper_local", "whisper_api"] = "whisper_local"
    model: str = "base"
    language: str | None = None


class TTSConfig(BaseModel):
    engine: Literal["edge", "elevenlabs"] = "edge"
    voice: str | None = None
    speed: float = 1.0
    elevenlabs_api_key: str | None = None


class BrainConfig(BaseModel):
    provider: Literal["openai", "anthropic", "ollama"] = "openai"
    model: str = "gpt-4o-mini"
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.7
    max_tokens: int = 500


class SpotifyConfig(BaseModel):
    enabled: bool = False
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = "http://localhost:8888/callback"
    device_name: str = "PiGlot"


class LearningConfig(BaseModel):
    session_duration_minutes: int = 15
    daily_goal_minutes: int = 30
    review_interval_hours: int = 24
    vocabulary_db: str = "data/vocabulary.db"
    progress_file: str = "data/progress.json"


class HardwareConfig(BaseModel):
    leds_enabled: bool = False
    button_pin: int | None = None
    led_pin: int | None = None


class PiGlotConfig(BaseModel):
    wake_word: str = "piglot"
    language: str = "es"
    target_language: str = "en"
    level: Literal["beginner", "intermediate", "advanced"] = "beginner"


class Config(BaseModel):
    piglot: PiGlotConfig = Field(default_factory=PiGlotConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    stt: STTConfig = Field(default_factory=STTConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    brain: BrainConfig = Field(default_factory=BrainConfig)
    spotify: SpotifyConfig = Field(default_factory=SpotifyConfig)
    learning: LearningConfig = Field(default_factory=LearningConfig)
    hardware: HardwareConfig = Field(default_factory=HardwareConfig)


def _resolve_env_vars(value: str) -> str:
    """Resolve ${ENV_VAR} patterns in strings."""
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        env_var = value[2:-1]
        return os.environ.get(env_var, "")
    return value


def _resolve_dict(d: dict) -> dict:
    """Recursively resolve env vars in a dict."""
    resolved = {}
    for k, v in d.items():
        if isinstance(v, dict):
            resolved[k] = _resolve_dict(v)
        elif isinstance(v, str):
            resolved[k] = _resolve_env_vars(v)
        else:
            resolved[k] = v
    return resolved


def load_config(path: str | Path = "config/config.yaml") -> Config:
    """Load configuration from YAML file."""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}\n"
            "Copy config/config.yaml.example to config/config.yaml and edit it."
        )
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    resolved = _resolve_dict(raw or {})
    return Config(**resolved)
