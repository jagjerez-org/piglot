"""
PiGlot Cloud Gateway

This is the server-side component that runs on YOUR infrastructure (VPS, cloud).
PiGlot devices connect ONLY to this gateway. The gateway then proxies to
external services (OpenAI, Spotify, etc).

Benefits:
- API keys never touch the device
- Per-device auth, usage tracking, rate limiting
- You can revoke a device instantly
- Central billing and monitoring
- Devices only need to know one URL

Architecture:
  PiGlot Device → [internet] → Gateway → OpenAI / Spotify / YouTube / etc.
       ↑                           ↑
  device_token              api_keys + secrets
  (revocable)               (safe on your server)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from aiohttp import web, ClientSession, ClientTimeout

logger = logging.getLogger("piglot.gateway")


# ─── Device Management ────────────────────────────────────────────────

@dataclass
class Device:
    """Registered PiGlot device."""
    device_id: str
    token_hash: str  # SHA-256 of device token (never store raw)
    name: str = ""
    owner: str = ""
    plan: str = "free"  # free | basic | premium
    created_at: str = ""
    last_seen: str = ""
    enabled: bool = True
    # Usage tracking
    requests_today: int = 0
    requests_total: int = 0
    tokens_used_today: int = 0
    last_reset: str = ""

    @property
    def daily_limit(self) -> int:
        limits = {"free": 100, "basic": 1000, "premium": 10000}
        return limits.get(self.plan, 100)


class DeviceRegistry:
    """Manage registered devices."""

    def __init__(self, db_path: str = "data/devices.json") -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.devices: dict[str, Device] = self._load()

    def _load(self) -> dict[str, Device]:
        if self.path.exists():
            data = json.loads(self.path.read_text())
            return {k: Device(**v) for k, v in data.items()}
        return {}

    def _save(self) -> None:
        data = {k: v.__dict__ for k, v in self.devices.items()}
        self.path.write_text(json.dumps(data, indent=2))

    def register_device(self, name: str = "", owner: str = "", plan: str = "free") -> tuple[str, str]:
        """Register a new device. Returns (device_id, raw_token)."""
        device_id = str(uuid.uuid4())[:8]
        raw_token = f"pgl_{uuid.uuid4().hex}"
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

        self.devices[device_id] = Device(
            device_id=device_id,
            token_hash=token_hash,
            name=name,
            owner=owner,
            plan=plan,
            created_at=datetime.utcnow().isoformat(),
        )
        self._save()
        return device_id, raw_token

    def authenticate(self, token: str) -> Device | None:
        """Authenticate a device by token. Returns Device or None."""
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        for device in self.devices.values():
            if device.token_hash == token_hash and device.enabled:
                return device
        return None

    def track_usage(self, device_id: str, tokens_used: int = 0) -> bool:
        """Track a request. Returns False if over limit."""
        device = self.devices.get(device_id)
        if not device:
            return False

        today = datetime.utcnow().date().isoformat()
        if device.last_reset != today:
            device.requests_today = 0
            device.tokens_used_today = 0
            device.last_reset = today

        if device.requests_today >= device.daily_limit:
            return False

        device.requests_today += 1
        device.requests_total += 1
        device.tokens_used_today += tokens_used
        device.last_seen = datetime.utcnow().isoformat()
        self._save()
        return True

    def revoke_device(self, device_id: str) -> bool:
        """Disable a device immediately."""
        device = self.devices.get(device_id)
        if device:
            device.enabled = False
            self._save()
            return True
        return False


# ─── Service Backends ─────────────────────────────────────────────────

@dataclass
class ServiceBackend:
    """Configuration for an upstream service."""
    name: str
    base_url: str
    api_key_env: str  # Environment variable name for the API key
    headers: dict[str, str] = field(default_factory=dict)
    timeout_seconds: int = 120


DEFAULT_BACKENDS: dict[str, ServiceBackend] = {
    "chat": ServiceBackend(
        name="openai_chat",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        headers={"Content-Type": "application/json"},
    ),
    "chat_anthropic": ServiceBackend(
        name="anthropic_chat",
        base_url="https://api.anthropic.com/v1",
        api_key_env="ANTHROPIC_API_KEY",
        headers={"Content-Type": "application/json", "anthropic-version": "2023-06-01"},
    ),
    "stt": ServiceBackend(
        name="openai_stt",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
    ),
    "tts": ServiceBackend(
        name="elevenlabs_tts",
        base_url="https://api.elevenlabs.io/v1",
        api_key_env="ELEVENLABS_API_KEY",
    ),
    "spotify": ServiceBackend(
        name="spotify",
        base_url="https://api.spotify.com/v1",
        api_key_env="SPOTIFY_ACCESS_TOKEN",
    ),
}


# ─── Gateway Server ──────────────────────────────────────────────────

class PiGlotGateway:
    """
    Cloud gateway server.

    Endpoints exposed to devices:
      POST /v1/chat          → LLM chat completion
      POST /v1/transcribe    → Speech-to-text
      POST /v1/synthesize    → Text-to-speech
      POST /v1/spotify/{action} → Spotify control
      GET  /v1/device/status → Device status + usage

    Admin endpoints:
      GET  /admin/devices         → List all devices
      POST /admin/devices         → Register new device
      POST /admin/devices/{id}/revoke → Revoke device
      GET  /admin/stats           → Usage statistics
    """

    def __init__(
        self,
        port: int = 443,
        backends: dict[str, ServiceBackend] | None = None,
        admin_token: str | None = None,
    ) -> None:
        self.port = port
        self.backends = backends or DEFAULT_BACKENDS
        self.registry = DeviceRegistry()
        self.admin_token = admin_token or os.environ.get("PIGLOT_ADMIN_TOKEN", "")
        self._session: ClientSession | None = None

    async def _get_session(self) -> ClientSession:
        if self._session is None or self._session.closed:
            self._session = ClientSession(timeout=ClientTimeout(total=120))
        return self._session

    # ─── Auth middleware ──────────────────────────────

    def _auth_device(self, request: web.Request) -> Device | None:
        """Authenticate device from Authorization header."""
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return None
        token = auth[7:]
        return self.registry.authenticate(token)

    def _auth_admin(self, request: web.Request) -> bool:
        """Authenticate admin from X-Admin-Token header."""
        token = request.headers.get("X-Admin-Token", "")
        return token == self.admin_token and self.admin_token != ""

    # ─── Device endpoints ─────────────────────────────

    async def handle_chat(self, request: web.Request) -> web.Response:
        """POST /v1/chat — Proxy chat to LLM."""
        device = self._auth_device(request)
        if not device:
            return web.json_response({"error": "unauthorized"}, status=401)
        if not self.registry.track_usage(device.device_id):
            return web.json_response({"error": "daily_limit_exceeded"}, status=429)

        body = await request.json()

        # Determine backend (default OpenAI, can specify anthropic)
        provider = body.pop("provider", "openai")
        backend = self.backends.get(
            "chat_anthropic" if provider == "anthropic" else "chat"
        )
        if not backend:
            return web.json_response({"error": "provider_not_configured"}, status=400)

        api_key = os.environ.get(backend.api_key_env, "")
        if not api_key:
            return web.json_response({"error": "provider_not_available"}, status=503)

        # Forward to provider
        session = await self._get_session()
        headers = {**backend.headers}

        if provider == "anthropic":
            headers["x-api-key"] = api_key
            url = f"{backend.base_url}/messages"
        else:
            headers["Authorization"] = f"Bearer {api_key}"
            url = f"{backend.base_url}/chat/completions"

        async with session.post(url, json=body, headers=headers) as resp:
            result = await resp.json()
            return web.json_response(result, status=resp.status)

    async def handle_transcribe(self, request: web.Request) -> web.Response:
        """POST /v1/transcribe — Proxy audio to Whisper API."""
        device = self._auth_device(request)
        if not device:
            return web.json_response({"error": "unauthorized"}, status=401)
        if not self.registry.track_usage(device.device_id):
            return web.json_response({"error": "daily_limit_exceeded"}, status=429)

        backend = self.backends.get("stt")
        if not backend:
            return web.json_response({"error": "stt_not_configured"}, status=503)

        api_key = os.environ.get(backend.api_key_env, "")
        session = await self._get_session()

        # Forward multipart form data
        data = await request.read()
        headers = {
            "Authorization": f"Bearer {api_key}",
        }
        # Pass through content-type with boundary
        ct = request.headers.get("Content-Type", "")
        if ct:
            headers["Content-Type"] = ct

        async with session.post(
            f"{backend.base_url}/audio/transcriptions",
            data=data,
            headers=headers,
        ) as resp:
            result = await resp.read()
            return web.Response(
                body=result,
                status=resp.status,
                content_type=resp.content_type,
            )

    async def handle_synthesize(self, request: web.Request) -> web.Response:
        """POST /v1/synthesize — Proxy text to TTS."""
        device = self._auth_device(request)
        if not device:
            return web.json_response({"error": "unauthorized"}, status=401)
        if not self.registry.track_usage(device.device_id):
            return web.json_response({"error": "daily_limit_exceeded"}, status=429)

        body = await request.json()
        text = body.get("text", "")
        voice = body.get("voice", "")
        engine = body.get("engine", "edge")

        if engine == "edge":
            # Edge TTS runs on the gateway itself (free, no API key needed)
            import edge_tts
            import tempfile

            communicate = edge_tts.Communicate(text, voice or "en-US-AriaNeural")
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                tmp_path = f.name
            try:
                await communicate.save(tmp_path)
                audio = Path(tmp_path).read_bytes()
                return web.Response(body=audio, content_type="audio/mpeg")
            finally:
                Path(tmp_path).unlink(missing_ok=True)

        elif engine == "elevenlabs":
            backend = self.backends.get("tts")
            if not backend:
                return web.json_response({"error": "tts_not_configured"}, status=503)
            api_key = os.environ.get(backend.api_key_env, "")
            session = await self._get_session()
            async with session.post(
                f"{backend.base_url}/text-to-speech/{voice}",
                json={"text": text, "model_id": "eleven_multilingual_v2"},
                headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            ) as resp:
                audio = await resp.read()
                return web.Response(body=audio, content_type="audio/mpeg", status=resp.status)

        return web.json_response({"error": "unknown_engine"}, status=400)

    async def handle_spotify(self, request: web.Request) -> web.Response:
        """POST /v1/spotify/{action} — Spotify control."""
        device = self._auth_device(request)
        if not device:
            return web.json_response({"error": "unauthorized"}, status=401)
        if not self.registry.track_usage(device.device_id):
            return web.json_response({"error": "daily_limit_exceeded"}, status=429)

        action = request.match_info.get("action", "")
        body = await request.json() if request.can_read_body else {}

        # TODO: Implement Spotify OAuth flow per-device
        # For now, uses a shared token
        spotify_token = os.environ.get("SPOTIFY_ACCESS_TOKEN", "")
        if not spotify_token:
            return web.json_response({"error": "spotify_not_configured"}, status=503)

        session = await self._get_session()
        headers = {"Authorization": f"Bearer {spotify_token}"}
        base = "https://api.spotify.com/v1"

        if action == "search":
            q = body.get("query", "")
            async with session.get(f"{base}/search?q={q}&type=track&limit=5", headers=headers) as resp:
                return web.json_response(await resp.json(), status=resp.status)
        elif action == "play":
            uri = body.get("uri", "")
            device_id = body.get("device_id")
            payload = {"uris": [uri]} if uri else {}
            url = f"{base}/me/player/play"
            if device_id:
                url += f"?device_id={device_id}"
            async with session.put(url, json=payload, headers=headers) as resp:
                return web.Response(status=resp.status)
        elif action == "pause":
            async with session.put(f"{base}/me/player/pause", headers=headers) as resp:
                return web.Response(status=resp.status)
        elif action == "next":
            async with session.post(f"{base}/me/player/next", headers=headers) as resp:
                return web.Response(status=resp.status)
        elif action == "devices":
            async with session.get(f"{base}/me/player/devices", headers=headers) as resp:
                return web.json_response(await resp.json(), status=resp.status)

        return web.json_response({"error": "unknown_action"}, status=400)

    async def handle_device_status(self, request: web.Request) -> web.Response:
        """GET /v1/device/status — Device info + usage."""
        device = self._auth_device(request)
        if not device:
            return web.json_response({"error": "unauthorized"}, status=401)

        return web.json_response({
            "device_id": device.device_id,
            "name": device.name,
            "plan": device.plan,
            "requests_today": device.requests_today,
            "daily_limit": device.daily_limit,
            "requests_total": device.requests_total,
            "enabled": device.enabled,
        })

    # ─── Admin endpoints ──────────────────────────────

    async def handle_admin_devices(self, request: web.Request) -> web.Response:
        """GET /admin/devices — List devices. POST to register."""
        if not self._auth_admin(request):
            return web.json_response({"error": "unauthorized"}, status=401)

        if request.method == "POST":
            body = await request.json()
            device_id, token = self.registry.register_device(
                name=body.get("name", ""),
                owner=body.get("owner", ""),
                plan=body.get("plan", "free"),
            )
            return web.json_response({
                "device_id": device_id,
                "token": token,  # Only shown once!
                "message": "Save this token — it won't be shown again.",
            })

        # GET
        devices = []
        for d in self.registry.devices.values():
            devices.append({
                "device_id": d.device_id,
                "name": d.name,
                "owner": d.owner,
                "plan": d.plan,
                "enabled": d.enabled,
                "requests_today": d.requests_today,
                "requests_total": d.requests_total,
                "last_seen": d.last_seen,
            })
        return web.json_response(devices)

    async def handle_admin_revoke(self, request: web.Request) -> web.Response:
        """POST /admin/devices/{id}/revoke — Revoke a device."""
        if not self._auth_admin(request):
            return web.json_response({"error": "unauthorized"}, status=401)

        device_id = request.match_info["id"]
        if self.registry.revoke_device(device_id):
            return web.json_response({"status": "revoked", "device_id": device_id})
        return web.json_response({"error": "device_not_found"}, status=404)

    async def handle_admin_stats(self, request: web.Request) -> web.Response:
        """GET /admin/stats — Overall statistics."""
        if not self._auth_admin(request):
            return web.json_response({"error": "unauthorized"}, status=401)

        devices = list(self.registry.devices.values())
        return web.json_response({
            "total_devices": len(devices),
            "active_devices": sum(1 for d in devices if d.enabled),
            "total_requests_today": sum(d.requests_today for d in devices),
            "total_requests_all_time": sum(d.requests_total for d in devices),
            "by_plan": {
                "free": sum(1 for d in devices if d.plan == "free"),
                "basic": sum(1 for d in devices if d.plan == "basic"),
                "premium": sum(1 for d in devices if d.plan == "premium"),
            },
        })

    # ─── App ──────────────────────────────────────────

    def create_app(self) -> web.Application:
        app = web.Application()

        # Device endpoints
        app.router.add_post("/v1/chat", self.handle_chat)
        app.router.add_post("/v1/transcribe", self.handle_transcribe)
        app.router.add_post("/v1/synthesize", self.handle_synthesize)
        app.router.add_post("/v1/spotify/{action}", self.handle_spotify)
        app.router.add_get("/v1/device/status", self.handle_device_status)

        # Admin endpoints
        app.router.add_route("*", "/admin/devices", self.handle_admin_devices)
        app.router.add_post("/admin/devices/{id}/revoke", self.handle_admin_revoke)
        app.router.add_get("/admin/stats", self.handle_admin_stats)

        return app

    async def start(self) -> None:
        app = self.create_app()
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self.port)
        await site.start()
        logger.info("🌐 PiGlot Gateway running on port %d", self.port)
