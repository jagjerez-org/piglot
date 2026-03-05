"""Wake word detection using OpenWakeWord."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from src.audio.capture import AudioCapture


class WakeWordDetector:
    """Detect wake word from audio stream."""

    def __init__(self, wake_word: str = "piglot", threshold: float = 0.5) -> None:
        self.wake_word = wake_word
        self.threshold = threshold
        self._model = None

    def _load_model(self) -> None:
        """Lazy-load the wake word model."""
        if self._model is None:
            from openwakeword.model import Model

            self._model = Model(
                wakeword_models=[self.wake_word],
                inference_framework="onnx",
            )

    async def listen(self, capture: AudioCapture) -> bool:
        """Listen for wake word. Returns True when detected."""
        self._load_model()
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._listen_sync, capture)

    def _listen_sync(self, capture: AudioCapture) -> bool:
        """Synchronous wake word listening."""
        import sounddevice as sd

        detected = False
        chunk_size = 1280  # ~80ms at 16kHz, required by openwakeword

        def callback(indata: np.ndarray, frames: int, time: object, status: object) -> None:
            nonlocal detected
            if detected:
                return
            audio_chunk = indata[:, 0].astype(np.int16)
            prediction = self._model.predict(audio_chunk)  # type: ignore[union-attr]
            for score in prediction.values():
                if score > self.threshold:
                    detected = True

        with sd.InputStream(
            samplerate=16000,
            channels=1,
            dtype="int16",
            blocksize=chunk_size,
            callback=callback,
        ):
            while not detected:
                sd.sleep(100)

        # Reset model state after detection
        self._model.reset()  # type: ignore[union-attr]
        return True
