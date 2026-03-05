"""
PiGlot Cloud Gateway — Intent-based architecture.

The device sends intents (structured requests). The gateway validates
permissions, checks rate limits, and ONLY THEN executes.

The LLM NEVER calls APIs directly. It produces intents. The gateway decides.

Flow:
  1. Pi captures voice → Whisper transcribes (on gateway)
  2. Gateway sends transcript to LLM → LLM returns intent JSON
  3. Gateway validates intent (schema + permissions + rate limit)
  4. Gateway executes intent (calls Spotify, YouTube, etc.)
  5. Gateway sends back: spoken reply + action result
  6. Pi speaks the reply

The Pi only makes 2 types of requests:
  POST /v1/turn    — "here's what the user said" (full pipeline)
  POST /v1/intent  — "execute this intent" (pre-parsed)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from aiohttp import web, ClientSession, ClientTimeout

from src.intents.schema import Intent, IntentType, validate_intent
from src.intents.extractor import build_system_prompt, parse_intent
from src.intents.executor import IntentExecutor

logger = logging.getLogger("piglot.gateway")


# ─── Device Management ────────────────────────────────────────────────

@dataclass
class Device:
    device_id: str
    token_hash: str
    name: str = ""
    owner: str = ""
    plan: str = "free"
    created_at: str = ""
    last_seen: str = ""
    enabled: bool = True
    native_lang: str = "es"
    target_lang: str = "en"
    level: str = "beginner"
    requests_today: int = 0
    requests_total: int = 0
    last_reset: str = ""

    @property
    def daily_limit(self) -> int:
        return {"free": 100, "basic": 1000, "premium": 10000}.get(self.plan, 100)


class DeviceRegistry:
    def __init__(self, db_path: str = "data/devices.json") -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.devices: dict[str, Device] = self._load()

    def _load(self) -> dict[str, Device]:
        if self.path.exists():
            return {k: Device(**v) for k, v in json.loads(self.path.read_text()).items()}
        return {}

    def _save(self) -> None:
        self.path.write_text(json.dumps({k: v.__dict__ for k, v in self.devices.items()}, indent=2))

    def register(self, name: str = "", owner: str = "", plan: str = "free",
                 native_lang: str = "es", target_lang: str = "en", level: str = "beginner") -> tuple[str, str]:
        device_id = str(uuid.uuid4())[:8]
        raw_token = f"pgl_{uuid.uuid4().hex}"
        self.devices[device_id] = Device(
            device_id=device_id,
            token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
            name=name, owner=owner, plan=plan,
            native_lang=native_lang, target_lang=target_lang, level=level,
            created_at=datetime.utcnow().isoformat(),
        )
        self._save()
        return device_id, raw_token

    def authenticate(self, token: str) -> Device | None:
        h = hashlib.sha256(token.encode()).hexdigest()
        for d in self.devices.values():
            if d.token_hash == h and d.enabled:
                return d
        return None

    def track_usage(self, device_id: str) -> bool:
        d = self.devices.get(device_id)
        if not d:
            return False
        today = datetime.utcnow().date().isoformat()
        if d.last_reset != today:
            d.requests_today = 0
            d.last_reset = today
        if d.requests_today >= d.daily_limit:
            return False
        d.requests_today += 1
        d.requests_total += 1
        d.last_seen = datetime.utcnow().isoformat()
        self._save()
        return True

    def revoke(self, device_id: str) -> bool:
        d = self.devices.get(device_id)
        if d:
            d.enabled = False
            self._save()
            return True
        return False


# ─── Gateway Server ──────────────────────────────────────────────────

class PiGlotGateway:
    def __init__(
        self,
        port: int = 8080,
        admin_token: str | None = None,
    ) -> None:
        self.port = port
        self.registry = DeviceRegistry()
        self.executor = IntentExecutor()
        self.admin_token = admin_token or os.environ.get("PIGLOT_ADMIN_TOKEN", "")
        self._llm_session: ClientSession | None = None

    async def _get_llm_session(self) -> ClientSession:
        if self._llm_session is None or self._llm_session.closed:
            self._llm_session = ClientSession(timeout=ClientTimeout(total=60))
        return self._llm_session

    def _auth_device(self, request: web.Request) -> Device | None:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return None
        return self.registry.authenticate(auth[7:])

    def _auth_admin(self, request: web.Request) -> bool:
        return request.headers.get("X-Admin-Token", "") == self.admin_token and self.admin_token != ""

    # ─── Core: Full turn (voice → intent → execute → reply) ────

    async def handle_turn(self, request: web.Request) -> web.Response:
        """
        POST /v1/turn

        The main endpoint. Device sends user's text, gateway:
        1. Builds prompt with device context + preferences
        2. Calls LLM → gets intent JSON
        3. Validates intent
        4. Executes intent
        5. Returns spoken reply + result

        Body: { "text": "pon música en francés", "history": [...] }
        """
        device = self._auth_device(request)
        if not device:
            return web.json_response({"error": "unauthorized"}, status=401)
        if not self.registry.track_usage(device.device_id):
            return web.json_response({"error": "daily_limit_exceeded"}, status=429)

        body = await request.json()
        user_text = body.get("text", "")
        history = body.get("history", [])

        if not user_text.strip():
            return web.json_response({"error": "empty_text"}, status=400)

        # 1. Get device preferences
        prefs = self.executor._preferences.get(device.device_id, {})

        # 2. Build LLM prompt
        system_prompt = build_system_prompt(
            native_lang=device.native_lang,
            target_lang=device.target_lang,
            level=device.level,
            preferences=prefs,
        )

        messages = [{"role": "system", "content": system_prompt}]
        # Add conversation history (limited)
        for msg in history[-20:]:
            messages.append(msg)
        messages.append({"role": "user", "content": user_text})

        # 3. Call LLM
        llm_response = await self._call_llm(messages, device)
        if llm_response is None:
            return web.json_response({"error": "llm_unavailable"}, status=503)

        # 4. Parse intent from LLM output
        intent = parse_intent(llm_response)

        # 5. Validate intent
        validation_error = validate_intent(intent, device.plan)
        if validation_error:
            logger.warning(
                "Intent rejected — device=%s action=%s error=%s",
                device.device_id, intent.action, validation_error,
            )
            # Don't tell the user about internal validation — just reply normally
            return web.json_response({
                "reply": intent.reply or "Sorry, I can't do that right now.",
                "intent": {"action": "reply", "executed": False},
            })

        # 6. Execute intent
        result = await self.executor.execute(intent, device.device_id, device.plan)

        # 7. Return reply + result
        return web.json_response({
            "reply": intent.reply,
            "intent": {
                "action": intent.action,
                "executed": result.success,
                "data": result.data,
                "error": result.error,
            },
        })

    async def _call_llm(self, messages: list[dict], device: Device) -> str | None:
        """Call the LLM provider. Returns raw text output."""
        session = await self._get_llm_session()

        # Try OpenAI first, then Anthropic
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")

        if openai_key:
            try:
                async with session.post(
                    "https://api.openai.com/v1/chat/completions",
                    json={
                        "model": os.environ.get("PIGLOT_MODEL", "gpt-4o-mini"),
                        "messages": messages,
                        "temperature": 0.7,
                        "max_tokens": 500,
                    },
                    headers={
                        "Authorization": f"Bearer {openai_key}",
                        "Content-Type": "application/json",
                    },
                ) as resp:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"]
            except Exception as e:
                logger.error("OpenAI call failed: %s", e)

        if anthropic_key:
            try:
                system = ""
                chat_msgs = []
                for m in messages:
                    if m["role"] == "system":
                        system = m["content"]
                    else:
                        chat_msgs.append(m)
                async with session.post(
                    "https://api.anthropic.com/v1/messages",
                    json={
                        "model": os.environ.get("PIGLOT_MODEL", "claude-sonnet-4-20250514"),
                        "system": system,
                        "messages": chat_msgs,
                        "max_tokens": 500,
                    },
                    headers={
                        "x-api-key": anthropic_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                ) as resp:
                    data = await resp.json()
                    return data["content"][0]["text"]
            except Exception as e:
                logger.error("Anthropic call failed: %s", e)

        return None

    # ─── Direct intent execution (pre-parsed) ────────

    async def handle_intent(self, request: web.Request) -> web.Response:
        """
        POST /v1/intent

        Execute a pre-parsed intent. For when the device handles LLM locally.

        Body: { "action": "spotify.play", "params": {"query": "..."}, "reply": "..." }
        """
        device = self._auth_device(request)
        if not device:
            return web.json_response({"error": "unauthorized"}, status=401)
        if not self.registry.track_usage(device.device_id):
            return web.json_response({"error": "daily_limit_exceeded"}, status=429)

        body = await request.json()

        try:
            intent = Intent(**body)
        except Exception as e:
            return web.json_response({"error": f"invalid_intent: {e}"}, status=400)

        validation_error = validate_intent(intent, device.plan)
        if validation_error:
            return web.json_response({"error": validation_error}, status=403)

        result = await self.executor.execute(intent, device.device_id, device.plan)
        return web.json_response({
            "success": result.success,
            "action": result.action,
            "data": result.data,
            "error": result.error,
        })

    # ─── Transcribe (STT on gateway) ─────────────────

    async def handle_transcribe(self, request: web.Request) -> web.Response:
        """POST /v1/transcribe — STT via Whisper API."""
        device = self._auth_device(request)
        if not device:
            return web.json_response({"error": "unauthorized"}, status=401)
        if not self.registry.track_usage(device.device_id):
            return web.json_response({"error": "daily_limit_exceeded"}, status=429)

        openai_key = os.environ.get("OPENAI_API_KEY", "")
        if not openai_key:
            return web.json_response({"error": "stt_not_configured"}, status=503)

        data = await request.read()
        ct = request.headers.get("Content-Type", "")
        session = await self._get_llm_session()

        async with session.post(
            "https://api.openai.com/v1/audio/transcriptions",
            data=data,
            headers={"Authorization": f"Bearer {openai_key}", "Content-Type": ct},
        ) as resp:
            return web.Response(body=await resp.read(), status=resp.status, content_type=resp.content_type)

    # ─── Synthesize (TTS on gateway) ─────────────────

    async def handle_synthesize(self, request: web.Request) -> web.Response:
        """POST /v1/synthesize — TTS via Edge TTS (free)."""
        device = self._auth_device(request)
        if not device:
            return web.json_response({"error": "unauthorized"}, status=401)

        body = await request.json()
        text = body.get("text", "")
        voice = body.get("voice", "en-US-AriaNeural")

        import edge_tts
        import tempfile

        communicate = edge_tts.Communicate(text, voice)
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp_path = f.name
        try:
            await communicate.save(tmp_path)
            audio = Path(tmp_path).read_bytes()
            return web.Response(body=audio, content_type="audio/mpeg")
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    # ─── Device status ───────────────────────────────

    async def handle_device_status(self, request: web.Request) -> web.Response:
        device = self._auth_device(request)
        if not device:
            return web.json_response({"error": "unauthorized"}, status=401)

        prefs = self.executor._preferences.get(device.device_id, {})
        vocab = self.executor._vocabulary.get(device.device_id, [])

        return web.json_response({
            "device_id": device.device_id,
            "name": device.name,
            "plan": device.plan,
            "requests_today": device.requests_today,
            "daily_limit": device.daily_limit,
            "native_lang": device.native_lang,
            "target_lang": device.target_lang,
            "level": device.level,
            "preferences": prefs,
            "vocabulary_count": len(vocab),
        })

    # ─── Admin endpoints ─────────────────────────────

    async def handle_admin_devices(self, request: web.Request) -> web.Response:
        if not self._auth_admin(request):
            return web.json_response({"error": "unauthorized"}, status=401)

        if request.method == "POST":
            body = await request.json()
            device_id, token = self.registry.register(
                name=body.get("name", ""),
                owner=body.get("owner", ""),
                plan=body.get("plan", "free"),
                native_lang=body.get("native_lang", "es"),
                target_lang=body.get("target_lang", "en"),
                level=body.get("level", "beginner"),
            )
            return web.json_response({
                "device_id": device_id,
                "token": token,
                "message": "Save this token — it won't be shown again.",
            })

        devices = [
            {
                "device_id": d.device_id, "name": d.name, "owner": d.owner,
                "plan": d.plan, "enabled": d.enabled,
                "requests_today": d.requests_today, "requests_total": d.requests_total,
                "last_seen": d.last_seen,
            }
            for d in self.registry.devices.values()
        ]
        return web.json_response(devices)

    async def handle_admin_revoke(self, request: web.Request) -> web.Response:
        if not self._auth_admin(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        device_id = request.match_info["id"]
        if self.registry.revoke(device_id):
            return web.json_response({"status": "revoked"})
        return web.json_response({"error": "not_found"}, status=404)

    async def handle_admin_stats(self, request: web.Request) -> web.Response:
        if not self._auth_admin(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        devices = list(self.registry.devices.values())
        return web.json_response({
            "total_devices": len(devices),
            "active": sum(1 for d in devices if d.enabled),
            "requests_today": sum(d.requests_today for d in devices),
            "requests_total": sum(d.requests_total for d in devices),
            "by_plan": {
                p: sum(1 for d in devices if d.plan == p)
                for p in ("free", "basic", "premium")
            },
        })

    # ─── App ─────────────────────────────────────────

    def create_app(self) -> web.Application:
        app = web.Application()

        # Device endpoints
        app.router.add_post("/v1/turn", self.handle_turn)
        app.router.add_post("/v1/intent", self.handle_intent)
        app.router.add_post("/v1/transcribe", self.handle_transcribe)
        app.router.add_post("/v1/synthesize", self.handle_synthesize)
        app.router.add_get("/v1/device/status", self.handle_device_status)

        # Admin
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
