"""Local Whisper STT engine."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from src.stt.engine import STTEngine


class WhisperLocalEngine(STTEngine):
    """Speech-to-text using local Whisper model."""

    def __init__(self, model_name: str = "base", language: str | None = None) -> None:
        self.model_name = model_name
        self.language = language
        self._model = None

    def _load_model(self):
        """Lazy-load Whisper model."""
        if self._model is None:
            import whisper
            self._model = whisper.load_model(self.model_name)
        return self._model

    async def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe audio numpy array to text."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._transcribe_sync, audio)

    def _transcribe_sync(self, audio: np.ndarray) -> str:
        """Synchronous transcription."""
        model = self._load_model()

        # Write to temp WAV file (Whisper expects file path or float32 array)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp_path = f.name
            sf.write(tmp_path, audio, 16000)

        try:
            options = {}
            if self.language:
                options["language"] = self.language

            result = model.transcribe(tmp_path, **options)
            return result["text"].strip()
        finally:
            Path(tmp_path).unlink(missing_ok=True)
