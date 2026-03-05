"""
PiGlot API Gateway / Proxy

All outbound traffic from PiGlot goes through this proxy.
Only whitelisted services and endpoints are allowed.
This prevents the device from being used for anything other than
its intended purpose (language learning + music).

Architecture:
  PiGlot modules → Proxy Gateway → Internet
                         ↓
                  Logs all requests
                  Enforces rate limits
                  Blocks unauthorized services
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aiohttp
from aiohttp import web

logger = logging.getLogger("piglot.proxy")


class ServiceAction(Enum):
    ALLOW = "allow"
    BLOCK = "block"
    LOG_ONLY = "log_only"  # Allow but flag for review


@dataclass
class ServiceRule:
    """Rule for an allowed service."""
    name: str
    domains: list[str]
    allowed_paths: list[str]  # prefix match, e.g. ["/v1/chat", "/v1/audio"]
    blocked_paths: list[str] = field(default_factory=list)
    max_requests_per_minute: int = 60
    max_request_body_kb: int = 1024  # 1MB default
    allowed_methods: list[str] = field(default_factory=lambda: ["GET", "POST"])
    require_auth_header: bool = False
    log_bodies: bool = False  # Don't log by default (privacy)


@dataclass
class RateLimitEntry:
    count: int = 0
    window_start: float = 0.0


# ─── Default service whitelist ───────────────────────────────────────────

DEFAULT_SERVICES: list[ServiceRule] = [
    # OpenAI (ChatGPT + Whisper)
    ServiceRule(
        name="openai",
        domains=["api.openai.com"],
        allowed_paths=[
            "/v1/chat/completions",
            "/v1/audio/transcriptions",
            "/v1/audio/translations",
        ],
        blocked_paths=[
            "/v1/files",        # No file uploads
            "/v1/fine_tuning",  # No fine-tuning
            "/v1/assistants",   # No assistants API
            "/v1/images",       # No image generation
        ],
        max_requests_per_minute=30,
        max_request_body_kb=5120,  # 5MB for audio
    ),
    # Anthropic (Claude)
    ServiceRule(
        name="anthropic",
        domains=["api.anthropic.com"],
        allowed_paths=["/v1/messages"],
        max_requests_per_minute=30,
    ),
    # Ollama (local)
    ServiceRule(
        name="ollama",
        domains=["localhost", "127.0.0.1"],
        allowed_paths=["/api/generate", "/api/chat", "/api/tags"],
        max_requests_per_minute=120,
        allowed_methods=["GET", "POST"],
    ),
    # Spotify Web API
    ServiceRule(
        name="spotify_api",
        domains=["api.spotify.com"],
        allowed_paths=[
            "/v1/search",
            "/v1/me/player",
            "/v1/me/player/play",
            "/v1/me/player/pause",
            "/v1/me/player/next",
            "/v1/me/player/previous",
            "/v1/me/player/devices",
            "/v1/me/player/currently-playing",
        ],
        blocked_paths=[
            "/v1/me/following",  # No social features
            "/v1/users",         # No user data access
        ],
        max_requests_per_minute=60,
    ),
    # Spotify Auth
    ServiceRule(
        name="spotify_auth",
        domains=["accounts.spotify.com"],
        allowed_paths=["/api/token", "/authorize"],
        max_requests_per_minute=10,
    ),
    # Edge TTS (Microsoft)
    ServiceRule(
        name="edge_tts",
        domains=[
            "speech.platform.bing.com",
            "eastus.api.speech.microsoft.com",
            "westus.api.speech.microsoft.com",
        ],
        allowed_paths=["/"],  # Allow all paths for TTS
        max_requests_per_minute=60,
        max_request_body_kb=256,
    ),
    # ElevenLabs TTS
    ServiceRule(
        name="elevenlabs",
        domains=["api.elevenlabs.io"],
        allowed_paths=["/v1/text-to-speech"],
        blocked_paths=[
            "/v1/voices/add",   # No voice cloning
            "/v1/history",      # No history access
        ],
        max_requests_per_minute=30,
    ),
    # YouTube (via yt-dlp, needs access to YouTube)
    ServiceRule(
        name="youtube",
        domains=[
            "www.youtube.com",
            "youtube.com",
            "youtu.be",
            "*.googlevideo.com",
            "*.youtube.com",
        ],
        allowed_paths=["/"],
        allowed_methods=["GET"],
        max_requests_per_minute=30,
    ),
    # Hugging Face (for downloading wake word / whisper models)
    ServiceRule(
        name="huggingface",
        domains=["huggingface.co", "cdn-lfs.huggingface.co"],
        allowed_paths=["/"],
        allowed_methods=["GET"],
        max_requests_per_minute=20,
    ),
]


class ProxyGateway:
    """
    HTTP proxy that only allows whitelisted services.
    
    Runs as a local HTTP proxy on the Pi. All PiGlot HTTP traffic
    is routed through it via environment variables:
      HTTP_PROXY=http://127.0.0.1:8899
      HTTPS_PROXY=http://127.0.0.1:8899
    """

    def __init__(
        self,
        services: list[ServiceRule] | None = None,
        port: int = 8899,
        log_dir: str = "data/proxy_logs",
    ) -> None:
        self.services = services or DEFAULT_SERVICES
        self.port = port
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._rate_limits: dict[str, RateLimitEntry] = {}
        self._request_log: list[dict[str, Any]] = []
        self._blocked_count = 0
        self._allowed_count = 0

    def _find_service(self, host: str) -> ServiceRule | None:
        """Find matching service rule for a host."""
        for svc in self.services:
            for domain in svc.domains:
                if domain.startswith("*"):
                    # Wildcard match
                    suffix = domain[1:]  # e.g. ".googlevideo.com"
                    if host.endswith(suffix):
                        return svc
                elif host == domain or host == f"{domain}":
                    return svc
        return None

    def _check_path(self, service: ServiceRule, path: str) -> bool:
        """Check if path is allowed for this service."""
        # Check blocked paths first
        for blocked in service.blocked_paths:
            if path.startswith(blocked):
                return False
        # Check allowed paths
        for allowed in service.allowed_paths:
            if allowed == "/" or path.startswith(allowed):
                return True
        return False

    def _check_rate_limit(self, service_name: str, max_rpm: int) -> bool:
        """Check rate limit. Returns True if allowed."""
        now = time.time()
        entry = self._rate_limits.get(service_name)
        if entry is None or now - entry.window_start > 60:
            self._rate_limits[service_name] = RateLimitEntry(count=1, window_start=now)
            return True
        if entry.count >= max_rpm:
            return False
        entry.count += 1
        return True

    def _log_request(
        self,
        method: str,
        url: str,
        service: str | None,
        action: str,
        reason: str = "",
    ) -> None:
        """Log request for audit trail."""
        entry = {
            "ts": time.time(),
            "method": method,
            "url": url,
            "service": service,
            "action": action,
            "reason": reason,
        }
        self._request_log.append(entry)
        
        # Keep log bounded
        if len(self._request_log) > 10000:
            self._request_log = self._request_log[-5000:]

        if action == "blocked":
            self._blocked_count += 1
            logger.warning("BLOCKED %s %s — %s", method, url, reason)
        else:
            self._allowed_count += 1
            logger.debug("ALLOWED %s %s → %s", method, url, service)

    async def handle_request(self, request: web.Request) -> web.Response:
        """Handle proxied HTTP request."""
        # Parse target URL
        target_url = str(request.url)
        
        # For CONNECT method (HTTPS tunneling)
        if request.method == "CONNECT":
            host = request.host.split(":")[0]
            service = self._find_service(host)
            if service is None:
                self._log_request("CONNECT", host, None, "blocked", "unknown service")
                return web.Response(status=403, text="Service not allowed")
            self._log_request("CONNECT", host, service.name, "allowed")
            # For real HTTPS proxy, you'd tunnel here. For simplicity,
            # PiGlot uses the proxy as a forward proxy with env vars.
            return web.Response(status=200)

        parsed = urlparse(target_url)
        host = parsed.hostname or ""
        path = parsed.path or "/"
        method = request.method

        # 1. Find matching service
        service = self._find_service(host)
        if service is None:
            self._log_request(method, target_url, None, "blocked", "no matching service")
            return web.Response(
                status=403,
                text=json.dumps({"error": "service_not_allowed", "host": host}),
                content_type="application/json",
            )

        # 2. Check method
        if method not in service.allowed_methods:
            self._log_request(method, target_url, service.name, "blocked", f"method {method} not allowed")
            return web.Response(
                status=405,
                text=json.dumps({"error": "method_not_allowed", "method": method}),
                content_type="application/json",
            )

        # 3. Check path
        if not self._check_path(service, path):
            self._log_request(method, target_url, service.name, "blocked", f"path {path} not allowed")
            return web.Response(
                status=403,
                text=json.dumps({"error": "path_not_allowed", "path": path}),
                content_type="application/json",
            )

        # 4. Check rate limit
        if not self._check_rate_limit(service.name, service.max_requests_per_minute):
            self._log_request(method, target_url, service.name, "blocked", "rate limit exceeded")
            return web.Response(
                status=429,
                text=json.dumps({"error": "rate_limit_exceeded", "service": service.name}),
                content_type="application/json",
            )

        # 5. Check body size
        body = await request.read()
        if len(body) > service.max_request_body_kb * 1024:
            self._log_request(method, target_url, service.name, "blocked", "body too large")
            return web.Response(
                status=413,
                text=json.dumps({"error": "body_too_large"}),
                content_type="application/json",
            )

        # 6. Forward request
        self._log_request(method, target_url, service.name, "allowed")

        headers = dict(request.headers)
        headers.pop("Host", None)
        headers.pop("host", None)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method=method,
                    url=target_url,
                    headers=headers,
                    data=body if body else None,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    resp_body = await resp.read()
                    return web.Response(
                        status=resp.status,
                        body=resp_body,
                        headers=dict(resp.headers),
                    )
        except Exception as e:
            logger.error("Proxy error for %s: %s", target_url, e)
            return web.Response(
                status=502,
                text=json.dumps({"error": "proxy_error", "detail": str(e)}),
                content_type="application/json",
            )

    async def handle_stats(self, request: web.Request) -> web.Response:
        """GET /_proxy/stats — proxy statistics."""
        return web.json_response({
            "allowed": self._allowed_count,
            "blocked": self._blocked_count,
            "services": [s.name for s in self.services],
            "rate_limits": {
                k: {"count": v.count, "window_start": v.window_start}
                for k, v in self._rate_limits.items()
            },
            "recent_blocked": [
                e for e in self._request_log[-50:]
                if e["action"] == "blocked"
            ],
        })

    async def handle_services(self, request: web.Request) -> web.Response:
        """GET /_proxy/services — list allowed services."""
        return web.json_response([
            {
                "name": s.name,
                "domains": s.domains,
                "allowed_paths": s.allowed_paths,
                "blocked_paths": s.blocked_paths,
                "rate_limit_rpm": s.max_requests_per_minute,
            }
            for s in self.services
        ])

    def create_app(self) -> web.Application:
        """Create the aiohttp application."""
        app = web.Application()
        # Admin endpoints (local only)
        app.router.add_get("/_proxy/stats", self.handle_stats)
        app.router.add_get("/_proxy/services", self.handle_services)
        # Catch-all proxy
        app.router.add_route("*", "/{path:.*}", self.handle_request)
        return app

    async def start(self) -> None:
        """Start the proxy server."""
        app = self.create_app()
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", self.port)
        await site.start()
        logger.info(
            "🛡️  PiGlot Proxy running on http://127.0.0.1:%d — %d services whitelisted",
            self.port,
            len(self.services),
        )


def load_custom_services(path: str = "config/proxy_services.json") -> list[ServiceRule]:
    """Load custom service rules from JSON file."""
    p = Path(path)
    if not p.exists():
        return DEFAULT_SERVICES
    
    data = json.loads(p.read_text())
    services = []
    for entry in data:
        services.append(ServiceRule(**entry))
    return services
