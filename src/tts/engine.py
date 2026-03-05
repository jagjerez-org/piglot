"""TTS engine interface and factory."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.config import TTSConfig

# Default voices per language for Edge TTS
DEFAULT_VOICES: dict[str, str] = {
    "en": "en-US-AriaNeural",
    "es": "es-ES-ElviraNeural",
    "fr": "fr-FR-DeniseNeural",
    "de": "de-DE-KatjaNeural",
    "it": "it-IT-ElsaNeural",
    "pt": "pt-BR-FranciscaNeural",
    "ja": "ja-JP-NanamiNeural",
    "ko": "ko-KR-SunHiNeural",
    "zh": "zh-CN-XiaoxiaoNeural",
    "ru": "ru-RU-SvetlanaNeural",
    "ar": "ar-SA-ZariyahNeural",
    "nl": "nl-NL-ColetteNeural",
}


class TTSEngine(ABC):
    """Abstract text-to-speech engine."""

    @abstractmethod
    async def synthesize(self, text: str) -> bytes:
        """Convert text to audio bytes (WAV format)."""
        ...


def create_tts_engine(config: TTSConfig, target_language: str) -> TTSEngine:
    """Factory to create TTS engine from config."""
    voice = config.voice or DEFAULT_VOICES.get(target_language, "en-US-AriaNeural")

    if config.engine == "edge":
        from src.tts.edge_tts import EdgeTTSEngine
        return EdgeTTSEngine(voice=voice, speed=config.speed)
    elif config.engine == "elevenlabs":
        from src.tts.elevenlabs import ElevenLabsTTSEngine
        return ElevenLabsTTSEngine(
            api_key=config.elevenlabs_api_key or "",
            voice=voice,
        )
    else:
        raise ValueError(f"Unknown TTS engine: {config.engine}")
