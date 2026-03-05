"""Audio capture from microphone."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import numpy as np
import sounddevice as sd

if TYPE_CHECKING:
    from src.config import AudioConfig


class AudioCapture:
    """Capture audio from microphone with silence detection."""

    def __init__(self, config: AudioConfig) -> None:
        self.config = config
        self.sample_rate = config.sample_rate
        self.silence_threshold = config.silence_threshold
        self.silence_duration = config.silence_duration
        self.max_record_seconds = config.max_record_seconds

    def _get_device(self) -> int | str:
        if self.config.input_device == "default":
            return sd.default.device[0]  # type: ignore[return-value]
        return self.config.input_device

    async def record_until_silence(self) -> np.ndarray | None:
        """Record audio until silence is detected. Returns numpy array or None."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._record_sync)

    def _record_sync(self) -> np.ndarray | None:
        """Synchronous recording with silence detection."""
        chunk_size = int(self.sample_rate * 0.1)  # 100ms chunks
        max_chunks = int(self.max_record_seconds * self.sample_rate / chunk_size)
        silence_chunks = int(self.silence_duration / 0.1)

        frames: list[np.ndarray] = []
        silent_count = 0
        has_speech = False

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=chunk_size,
            device=self._get_device(),
        ) as stream:
            for _ in range(max_chunks):
                data, _ = stream.read(chunk_size)
                frames.append(data.copy())

                rms = np.sqrt(np.mean(data.astype(np.float32) ** 2))

                if rms > self.silence_threshold:
                    has_speech = True
                    silent_count = 0
                else:
                    silent_count += 1

                if has_speech and silent_count >= silence_chunks:
                    break

        if not has_speech:
            return None

        return np.concatenate(frames)

    def get_stream(self, callback: callable) -> sd.InputStream:  # type: ignore[type-arg]
        """Get a continuous input stream for wake word detection."""
        return sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=int(self.sample_rate * 0.1),
            device=self._get_device(),
            callback=callback,
        )
