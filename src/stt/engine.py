"""STT engine interface and factory."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from src.config import STTConfig


class STTEngine(ABC):
    """Abstract speech-to-text engine."""

    @abstractmethod
    async def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe audio to text."""
        ...


def create_stt_engine(config: STTConfig) -> STTEngine:
    """Factory to create STT engine from config."""
    if config.engine == "whisper_local":
        from src.stt.whisper_local import WhisperLocalEngine
        return WhisperLocalEngine(model_name=config.model, language=config.language)
    elif config.engine == "whisper_api":
        from src.stt.whisper_api import WhisperAPIEngine
        return WhisperAPIEngine(language=config.language)
    else:
        raise ValueError(f"Unknown STT engine: {config.engine}")
