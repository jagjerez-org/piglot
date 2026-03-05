"""
Intent Schema — The contract between LLM and Gateway.

The LLM can ONLY produce these intents. The gateway ONLY executes these.
Anything outside this schema is rejected.

This is the security boundary.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class IntentType(str, Enum):
    """All possible actions. If it's not here, it doesn't exist."""

    # ─── Conversation (always allowed) ──────────
    REPLY = "reply"                        # Just respond to user (no side effects)

    # ─── Spotify ────────────────────────────────
    SPOTIFY_PLAY = "spotify.play"          # Play a track/playlist
    SPOTIFY_PAUSE = "spotify.pause"        # Pause playback
    SPOTIFY_RESUME = "spotify.resume"      # Resume playback
    SPOTIFY_SKIP = "spotify.skip"          # Skip to next track
    SPOTIFY_SEARCH = "spotify.search"      # Search for music
    SPOTIFY_NOW_PLAYING = "spotify.now_playing"  # What's playing?

    # ─── YouTube ────────────────────────────────
    YOUTUBE_PLAY = "youtube.play"          # Play audio from YouTube
    YOUTUBE_SEARCH = "youtube.search"      # Search YouTube

    # ─── Learning ───────────────────────────────
    VOCAB_ADD = "learning.vocab_add"       # Add word to vocabulary
    VOCAB_QUIZ = "learning.vocab_quiz"     # Start vocabulary quiz
    VOCAB_STATS = "learning.vocab_stats"   # Get vocabulary stats
    PROGRESS = "learning.progress"         # Get learning progress

    # ─── Preferences ────────────────────────────
    PREF_SET = "preferences.set"           # Save a preference
    PREF_GET = "preferences.get"           # Read a preference

    # ─── System ─────────────────────────────────
    VOLUME_SET = "system.volume"           # Set speaker volume
    TIMER_SET = "system.timer"             # Set a timer
    DEVICE_STATUS = "system.status"        # Get device info


class Intent(BaseModel):
    """
    An intent produced by the LLM.

    The LLM fills this out. The gateway validates and executes it.
    The LLM CANNOT add new fields or actions.
    """

    action: IntentType
    params: dict[str, Any] = Field(default_factory=dict)
    # The spoken response to the user (always present)
    reply: str = ""

    class Config:
        extra = "forbid"  # Reject any extra fields


class IntentResult(BaseModel):
    """Result from the gateway after executing an intent."""

    success: bool
    action: str
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


# ─── Permission matrix ────────────────────────────────────────────────

# Which plans can use which intents
PLAN_PERMISSIONS: dict[str, set[IntentType]] = {
    "free": {
        IntentType.REPLY,
        IntentType.VOCAB_ADD,
        IntentType.VOCAB_QUIZ,
        IntentType.VOCAB_STATS,
        IntentType.PROGRESS,
        IntentType.PREF_SET,
        IntentType.PREF_GET,
        IntentType.DEVICE_STATUS,
    },
    "basic": {
        # Everything in free, plus:
        IntentType.REPLY,
        IntentType.SPOTIFY_PLAY,
        IntentType.SPOTIFY_PAUSE,
        IntentType.SPOTIFY_RESUME,
        IntentType.SPOTIFY_SKIP,
        IntentType.SPOTIFY_SEARCH,
        IntentType.SPOTIFY_NOW_PLAYING,
        IntentType.VOCAB_ADD,
        IntentType.VOCAB_QUIZ,
        IntentType.VOCAB_STATS,
        IntentType.PROGRESS,
        IntentType.PREF_SET,
        IntentType.PREF_GET,
        IntentType.VOLUME_SET,
        IntentType.TIMER_SET,
        IntentType.DEVICE_STATUS,
    },
    "premium": {
        # Everything
        *IntentType,
    },
}


# ─── Parameter schemas per intent (for validation) ───────────────────

PARAM_SCHEMAS: dict[IntentType, dict[str, type]] = {
    IntentType.REPLY: {},
    IntentType.SPOTIFY_PLAY: {"query": str},
    IntentType.SPOTIFY_PAUSE: {},
    IntentType.SPOTIFY_RESUME: {},
    IntentType.SPOTIFY_SKIP: {},
    IntentType.SPOTIFY_SEARCH: {"query": str},
    IntentType.SPOTIFY_NOW_PLAYING: {},
    IntentType.YOUTUBE_PLAY: {"query": str},
    IntentType.YOUTUBE_SEARCH: {"query": str},
    IntentType.VOCAB_ADD: {"word": str, "translation": str},
    IntentType.VOCAB_QUIZ: {},
    IntentType.VOCAB_STATS: {},
    IntentType.PROGRESS: {},
    IntentType.PREF_SET: {"key": str, "value": str},
    IntentType.PREF_GET: {"key": str},
    IntentType.VOLUME_SET: {"level": int},
    IntentType.TIMER_SET: {"seconds": int},
    IntentType.DEVICE_STATUS: {},
}


def validate_intent(intent: Intent, plan: str = "free") -> str | None:
    """
    Validate an intent. Returns error message or None if valid.

    This runs on the GATEWAY side, not on the device.
    """
    # 1. Check plan permission
    allowed = PLAN_PERMISSIONS.get(plan, PLAN_PERMISSIONS["free"])
    if intent.action not in allowed:
        return f"Action '{intent.action}' not available on plan '{plan}'"

    # 2. Check required params
    expected = PARAM_SCHEMAS.get(intent.action, {})
    for param_name, param_type in expected.items():
        if param_name not in intent.params:
            return f"Missing required param: {param_name}"
        if not isinstance(intent.params[param_name], param_type):
            return f"Param '{param_name}' must be {param_type.__name__}"

    # 3. Check no unexpected params (defense against injection)
    allowed_params = set(expected.keys())
    extra = set(intent.params.keys()) - allowed_params
    if extra:
        return f"Unexpected params: {extra}"

    return None
