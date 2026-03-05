"""
PiGlot Gateway Client

This runs on the Raspberry Pi. It replaces direct API calls —
everything goes through YOUR gateway.

The device only needs:
  1. Gateway URL (e.g. https://api.piglot.com)
  2. Device token (e.g. pgl_abc123...)

No API keys on the device. Ever.
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp


class GatewayClient:
    """Client for PiGlot Cloud Gateway."""

    def __init__(self, gateway_url: str, device_token: str) -> None:
        self.gateway_url = gateway_url.rstrip("/")
        self.device_token = device_token
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"Authorization": f"Bearer {self.device_token}"},
                timeout=aiohttp.ClientTimeout(total=120),
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ─── Chat (LLM) ──────────────────────────────────

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str = "gpt-4o-mini",
        provider: str = "openai",
        temperature: float = 0.7,
        max_tokens: int = 500,
    ) -> str:
        """Send chat completion through gateway."""
        session = await self._get_session()
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "provider": provider,
        }

        async with session.post(f"{self.gateway_url}/v1/chat", json=payload) as resp:
            if resp.status == 401:
                raise PermissionError("Device not authorized")
            if resp.status == 429:
                raise RuntimeError("Daily request limit exceeded")
            resp.raise_for_status()
            data = await resp.json()

        # Handle both OpenAI and Anthropic response formats
        if "choices" in data:
            return data["choices"][0]["message"]["content"]
        elif "content" in data:
            return data["content"][0]["text"]
        return str(data)

    # ─── Speech-to-Text ───────────────────────────────

    async def transcribe(self, audio_bytes: bytes, language: str | None = None) -> str:
        """Transcribe audio through gateway."""
        session = await self._get_session()

        form = aiohttp.FormData()
        form.add_field("file", audio_bytes, filename="audio.wav", content_type="audio/wav")
        form.add_field("model", "whisper-1")
        if language:
            form.add_field("language", language)

        async with session.post(f"{self.gateway_url}/v1/transcribe", data=form) as resp:
            if resp.status == 401:
                raise PermissionError("Device not authorized")
            resp.raise_for_status()
            data = await resp.json()
            return data.get("text", "")

    # ─── Text-to-Speech ───────────────────────────────

    async def synthesize(
        self,
        text: str,
        voice: str = "en-US-AriaNeural",
        engine: str = "edge",
    ) -> bytes:
        """Synthesize speech through gateway."""
        session = await self._get_session()
        payload = {"text": text, "voice": voice, "engine": engine}

        async with session.post(f"{self.gateway_url}/v1/synthesize", json=payload) as resp:
            if resp.status == 401:
                raise PermissionError("Device not authorized")
            resp.raise_for_status()
            return await resp.read()

    # ─── Spotify ──────────────────────────────────────

    async def spotify_search(self, query: str) -> dict:
        session = await self._get_session()
        async with session.post(
            f"{self.gateway_url}/v1/spotify/search",
            json={"query": query},
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def spotify_play(self, uri: str, device_id: str | None = None) -> None:
        session = await self._get_session()
        payload: dict[str, Any] = {"uri": uri}
        if device_id:
            payload["device_id"] = device_id
        async with session.post(
            f"{self.gateway_url}/v1/spotify/play", json=payload
        ) as resp:
            resp.raise_for_status()

    async def spotify_pause(self) -> None:
        session = await self._get_session()
        async with session.post(f"{self.gateway_url}/v1/spotify/pause") as resp:
            resp.raise_for_status()

    async def spotify_next(self) -> None:
        session = await self._get_session()
        async with session.post(f"{self.gateway_url}/v1/spotify/next") as resp:
            resp.raise_for_status()

    async def spotify_devices(self) -> dict:
        session = await self._get_session()
        async with session.post(f"{self.gateway_url}/v1/spotify/devices") as resp:
            resp.raise_for_status()
            return await resp.json()

    # ─── Device Status ────────────────────────────────

    async def status(self) -> dict:
        """Get device status and usage info."""
        session = await self._get_session()
        async with session.get(f"{self.gateway_url}/v1/device/status") as resp:
            resp.raise_for_status()
            return await resp.json()
