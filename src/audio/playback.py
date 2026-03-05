"""Audio playback to speaker."""

from __future__ import annotations

import asyncio
import io
from typing import TYPE_CHECKING

import sounddevice as sd
import soundfile as sf

if TYPE_CHECKING:
    from src.config import AudioConfig


class AudioPlayback:
    """Play audio through speaker."""

    def __init__(self, config: AudioConfig) -> None:
        self.config = config

    def _get_device(self) -> int | str:
        if self.config.output_device == "default":
            return sd.default.device[1]  # type: ignore[return-value]
        return self.config.output_device

    async def play(self, audio_data: bytes) -> None:
        """Play audio bytes (WAV/MP3 format)."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._play_sync, audio_data)

    def _play_sync(self, audio_data: bytes) -> None:
        """Synchronous audio playback."""
        data, samplerate = sf.read(io.BytesIO(audio_data))
        sd.play(data, samplerate, device=self._get_device())
        sd.wait()
