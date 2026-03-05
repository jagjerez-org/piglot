"""
Intent Executor — Runs on the GATEWAY side.

Receives validated intents from devices and executes them.
The device never calls external APIs — only sends intents here.

Security chain:
  1. Device sends intent + device_token
  2. Gateway authenticates device
  3. Gateway validates intent against schema
  4. Gateway checks plan permissions
  5. Gateway checks rate limits
  6. Only THEN does it execute
"""

from __future__ import annotations

import logging
import os
from typing import Any

import aiohttp

from src.intents.schema import Intent, IntentResult, IntentType, validate_intent

logger = logging.getLogger("piglot.executor")


class IntentExecutor:
    """Executes validated intents on the gateway side."""

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        # Per-device preferences stored in memory (in production, use a DB)
        self._preferences: dict[str, dict[str, str]] = {}
        # Per-device vocabulary (in production, use a DB)
        self._vocabulary: dict[str, list[dict[str, str]]] = {}

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def execute(self, intent: Intent, device_id: str, plan: str) -> IntentResult:
        """
        Validate and execute an intent.

        This is the ONLY place where external APIs are called.
        """
        # 1. Validate intent
        error = validate_intent(intent, plan)
        if error:
            logger.warning("Intent rejected for device %s: %s", device_id, error)
            return IntentResult(success=False, action=intent.action, error=error)

        # 2. Execute based on action
        try:
            handler = self._get_handler(intent.action)
            if handler is None:
                return IntentResult(
                    success=True,
                    action=intent.action,
                    data={"reply": intent.reply},
                )
            result = await handler(intent, device_id)
            return result
        except Exception as e:
            logger.error("Intent execution failed: %s — %s", intent.action, e)
            return IntentResult(
                success=False,
                action=intent.action,
                error=f"Execution failed: {str(e)}",
            )

    def _get_handler(self, action: IntentType):
        """Map action to handler method."""
        handlers = {
            IntentType.REPLY: None,  # No side effects
            IntentType.SPOTIFY_PLAY: self._spotify_play,
            IntentType.SPOTIFY_PAUSE: self._spotify_pause,
            IntentType.SPOTIFY_RESUME: self._spotify_resume,
            IntentType.SPOTIFY_SKIP: self._spotify_skip,
            IntentType.SPOTIFY_SEARCH: self._spotify_search,
            IntentType.SPOTIFY_NOW_PLAYING: self._spotify_now_playing,
            IntentType.YOUTUBE_PLAY: self._youtube_search,  # Search, return URL
            IntentType.YOUTUBE_SEARCH: self._youtube_search,
            IntentType.VOCAB_ADD: self._vocab_add,
            IntentType.VOCAB_QUIZ: self._vocab_quiz,
            IntentType.VOCAB_STATS: self._vocab_stats,
            IntentType.PROGRESS: self._progress,
            IntentType.PREF_SET: self._pref_set,
            IntentType.PREF_GET: self._pref_get,
            IntentType.VOLUME_SET: None,  # Executed locally on Pi
            IntentType.TIMER_SET: None,   # Executed locally on Pi
            IntentType.DEVICE_STATUS: None,  # Handled by device endpoint
        }
        return handlers.get(action)

    # ─── Spotify handlers ─────────────────────────────

    async def _spotify_request(
        self, method: str, path: str, json_data: dict | None = None
    ) -> dict:
        """Make authenticated Spotify API request."""
        token = os.environ.get("SPOTIFY_ACCESS_TOKEN", "")
        if not token:
            raise RuntimeError("Spotify not configured")
        session = await self._get_session()
        url = f"https://api.spotify.com/v1{path}"
        headers = {"Authorization": f"Bearer {token}"}
        async with session.request(method, url, headers=headers, json=json_data) as resp:
            if resp.content_type == "application/json":
                return await resp.json()
            return {"status": resp.status}

    async def _spotify_play(self, intent: Intent, device_id: str) -> IntentResult:
        query = intent.params["query"]
        # Search first
        results = await self._spotify_request(
            "GET", f"/search?q={query}&type=track&limit=1"
        )
        tracks = results.get("tracks", {}).get("items", [])
        if not tracks:
            return IntentResult(
                success=False, action=intent.action,
                error=f"No tracks found for: {query}",
            )
        track = tracks[0]
        # Play
        await self._spotify_request("PUT", "/me/player/play", {"uris": [track["uri"]]})
        return IntentResult(
            success=True, action=intent.action,
            data={"track": track["name"], "artist": track["artists"][0]["name"]},
        )

    async def _spotify_pause(self, intent: Intent, device_id: str) -> IntentResult:
        await self._spotify_request("PUT", "/me/player/pause")
        return IntentResult(success=True, action=intent.action)

    async def _spotify_resume(self, intent: Intent, device_id: str) -> IntentResult:
        await self._spotify_request("PUT", "/me/player/play")
        return IntentResult(success=True, action=intent.action)

    async def _spotify_skip(self, intent: Intent, device_id: str) -> IntentResult:
        await self._spotify_request("POST", "/me/player/next")
        return IntentResult(success=True, action=intent.action)

    async def _spotify_search(self, intent: Intent, device_id: str) -> IntentResult:
        query = intent.params["query"]
        results = await self._spotify_request(
            "GET", f"/search?q={query}&type=track&limit=5"
        )
        tracks = [
            {"name": t["name"], "artist": t["artists"][0]["name"], "uri": t["uri"]}
            for t in results.get("tracks", {}).get("items", [])
        ]
        return IntentResult(success=True, action=intent.action, data={"tracks": tracks})

    async def _spotify_now_playing(self, intent: Intent, device_id: str) -> IntentResult:
        result = await self._spotify_request("GET", "/me/player/currently-playing")
        item = result.get("item")
        if not item:
            return IntentResult(
                success=True, action=intent.action,
                data={"playing": False},
            )
        return IntentResult(
            success=True, action=intent.action,
            data={
                "playing": True,
                "track": item["name"],
                "artist": item["artists"][0]["name"],
            },
        )

    # ─── YouTube handlers ─────────────────────────────

    async def _youtube_search(self, intent: Intent, device_id: str) -> IntentResult:
        """Search YouTube. Returns URLs for the device to play via yt-dlp."""
        query = intent.params["query"]
        # Use Invidious API (no API key needed, privacy-friendly)
        session = await self._get_session()
        async with session.get(
            f"https://vid.puffyan.us/api/v1/search?q={query}&type=video&limit=3"
        ) as resp:
            if resp.status != 200:
                return IntentResult(
                    success=False, action=intent.action,
                    error="YouTube search failed",
                )
            results = await resp.json()

        videos = [
            {
                "title": v.get("title", ""),
                "video_id": v.get("videoId", ""),
                "url": f"https://www.youtube.com/watch?v={v.get('videoId', '')}",
                "length_seconds": v.get("lengthSeconds", 0),
            }
            for v in results[:3]
        ]
        return IntentResult(success=True, action=intent.action, data={"videos": videos})

    # ─── Learning handlers ────────────────────────────

    async def _vocab_add(self, intent: Intent, device_id: str) -> IntentResult:
        words = self._vocabulary.setdefault(device_id, [])
        word_entry = {
            "word": intent.params["word"],
            "translation": intent.params["translation"],
        }
        # Dedup
        if not any(w["word"] == word_entry["word"] for w in words):
            words.append(word_entry)
        return IntentResult(
            success=True, action=intent.action,
            data={"total_words": len(words)},
        )

    async def _vocab_quiz(self, intent: Intent, device_id: str) -> IntentResult:
        words = self._vocabulary.get(device_id, [])
        if not words:
            return IntentResult(
                success=True, action=intent.action,
                data={"quiz": None, "message": "No words saved yet"},
            )
        import random
        word = random.choice(words)
        return IntentResult(
            success=True, action=intent.action,
            data={"quiz_word": word["word"], "expected": word["translation"]},
        )

    async def _vocab_stats(self, intent: Intent, device_id: str) -> IntentResult:
        words = self._vocabulary.get(device_id, [])
        return IntentResult(
            success=True, action=intent.action,
            data={"total_words": len(words)},
        )

    async def _progress(self, intent: Intent, device_id: str) -> IntentResult:
        words = self._vocabulary.get(device_id, [])
        prefs = self._preferences.get(device_id, {})
        return IntentResult(
            success=True, action=intent.action,
            data={
                "total_words": len(words),
                "preferences_set": len(prefs),
            },
        )

    # ─── Preference handlers ─────────────────────────

    async def _pref_set(self, intent: Intent, device_id: str) -> IntentResult:
        prefs = self._preferences.setdefault(device_id, {})
        key = intent.params["key"]
        value = intent.params["value"]
        # Limit keys to prevent abuse
        ALLOWED_PREF_KEYS = {
            "favorite_topics", "music_genre", "difficulty_preference",
            "conversation_style", "native_language", "target_language",
            "name", "interests", "correction_level",
        }
        if key not in ALLOWED_PREF_KEYS:
            return IntentResult(
                success=False, action=intent.action,
                error=f"Unknown preference key: {key}. Allowed: {ALLOWED_PREF_KEYS}",
            )
        prefs[key] = value
        return IntentResult(success=True, action=intent.action, data={"key": key})

    async def _pref_get(self, intent: Intent, device_id: str) -> IntentResult:
        prefs = self._preferences.get(device_id, {})
        key = intent.params["key"]
        value = prefs.get(key)
        return IntentResult(
            success=True, action=intent.action,
            data={"key": key, "value": value},
        )
