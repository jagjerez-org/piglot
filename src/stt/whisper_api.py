"""OpenAI Whisper API STT engine."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from openai import OpenAI

from src.stt.engine import STTEngine


class WhisperAPIEngine(STTEngine):
    """Speech-to-text using OpenAI Whisper API."""

    def __init__(self, language: str | None = None) -> None:
        self.language = language
        self.client = OpenAI()

    async def transcribe(self, audio: np.ndarray) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._transcribe_sync, audio)

    def _transcribe_sync(self, audio: np.ndarray) -> str:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp_path = f.name
            sf.write(tmp_path, audio, 16000)

        try:
            with open(tmp_path, "rb") as audio_file:
                kwargs = {"model": "whisper-1", "file": audio_file}
                if self.language:
                    kwargs["language"] = self.language
                result = self.client.audio.transcriptions.create(**kwargs)
            return result.text.strip()
        finally:
            Path(tmp_path).unlink(missing_ok=True)
