"""
PiGlot Gateway Client — Intent-based.

Runs on the Raspberry Pi. Sends user speech to the gateway,
gets back a spoken reply + action results.

The Pi NEVER calls external APIs. It only talks to the gateway.
The Pi NEVER runs the LLM. The gateway does.
"""

from __future__ import annotations

from typing import Any

import aiohttp


class TurnResult:
    """Result from a conversation turn."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.reply: str = data.get("reply", "")
        self.intent: dict[str, Any] = data.get("intent", {})
        self.action: str = self.intent.get("action", "reply")
        self.executed: bool = self.intent.get("executed", False)
        self.data: dict[str, Any] = self.intent.get("data", {})
        self.error: str | None = self.intent.get("error")


class GatewayClient:
    """Client for PiGlot Cloud Gateway. All intelligence is server-side."""

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

    # ─── Main: Conversation Turn ──────────────────────

    async def turn(self, text: str, history: list[dict[str, str]] | None = None) -> TurnResult:
        """
        Send user's text to gateway. Gateway runs LLM + executes intent.

        Returns:
          - reply: what to speak back to the user
          - action: what was executed (or "reply" for plain conversation)
          - data: action-specific data (e.g. track info for spotify.play)

        This is the ONLY method you need for the main loop.
        """
        session = await self._get_session()
        payload = {"text": text, "history": history or []}

        async with session.post(f"{self.gateway_url}/v1/turn", json=payload) as resp:
            if resp.status == 401:
                raise PermissionError("Device not authorized. Check your token.")
            if resp.status == 429:
                raise RuntimeError("Daily request limit exceeded. Try again tomorrow.")
            resp.raise_for_status()
            return TurnResult(await resp.json())

    # ─── Speech-to-Text ───────────────────────────────

    async def transcribe(self, audio_bytes: bytes, language: str | None = None) -> str:
        """Send audio to gateway for transcription."""
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

    async def synthesize(self, text: str, voice: str = "en-US-AriaNeural") -> bytes:
        """Get audio from gateway TTS."""
        session = await self._get_session()
        async with session.post(
            f"{self.gateway_url}/v1/synthesize",
            json={"text": text, "voice": voice},
        ) as resp:
            if resp.status == 401:
                raise PermissionError("Device not authorized")
            resp.raise_for_status()
            return await resp.read()

    # ─── Device Status ────────────────────────────────

    async def status(self) -> dict:
        session = await self._get_session()
        async with session.get(f"{self.gateway_url}/v1/device/status") as resp:
            resp.raise_for_status()
            return await resp.json()
