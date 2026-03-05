"""Edge TTS engine (free, Microsoft)."""

from __future__ import annotations

import asyncio
import io
import tempfile
from pathlib import Path

import edge_tts

from src.tts.engine import TTSEngine


class EdgeTTSEngine(TTSEngine):
    """Free TTS using Microsoft Edge voices."""

    def __init__(self, voice: str = "en-US-AriaNeural", speed: float = 1.0) -> None:
        self.voice = voice
        # Edge TTS uses rate like "+0%", "-10%", "+20%"
        speed_pct = int((speed - 1.0) * 100)
        self.rate = f"{speed_pct:+d}%"

    async def synthesize(self, text: str) -> bytes:
        """Convert text to WAV audio bytes."""
        communicate = edge_tts.Communicate(text, self.voice, rate=self.rate)

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp_path = f.name

        try:
            await communicate.save(tmp_path)
            return Path(tmp_path).read_bytes()
        finally:
            Path(tmp_path).unlink(missing_ok=True)
