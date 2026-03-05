"""ElevenLabs TTS engine (premium)."""

from __future__ import annotations

import asyncio

from src.tts.engine import TTSEngine


class ElevenLabsTTSEngine(TTSEngine):
    """Premium TTS using ElevenLabs API."""

    def __init__(self, api_key: str, voice: str = "Rachel") -> None:
        self.api_key = api_key
        self.voice = voice
        self._client = None

    def _get_client(self):
        if self._client is None:
            from elevenlabs.client import ElevenLabs
            self._client = ElevenLabs(api_key=self.api_key)
        return self._client

    async def synthesize(self, text: str) -> bytes:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._synthesize_sync, text)

    def _synthesize_sync(self, text: str) -> bytes:
        client = self._get_client()
        audio_iter = client.generate(
            text=text,
            voice=self.voice,
            model="eleven_multilingual_v2",
        )
        return b"".join(audio_iter)
