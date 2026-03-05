"""
Intent Extractor — Makes the LLM produce structured intents.

The LLM receives the user's message and MUST respond with:
1. A spoken reply (what to say back)
2. An optional intent (an action to execute)

The LLM NEVER executes anything. It only declares what it wants.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.intents.schema import Intent, IntentType

logger = logging.getLogger("piglot.intents")

# This prompt constrains the LLM to ONLY produce valid intents
INTENT_SYSTEM_PROMPT = """You are PiGlot, a language learning voice assistant.

You MUST respond in this exact JSON format, nothing else:

```json
{{
  "action": "<action_type>",
  "params": {{}},
  "reply": "<what you say to the user>"
}}
```

AVAILABLE ACTIONS:
- "reply" — Just respond, no side effects (params: {{}})
- "spotify.play" — Play music (params: {{"query": "song or artist"}})
- "spotify.pause" — Pause music (params: {{}})
- "spotify.resume" — Resume music (params: {{}})
- "spotify.skip" — Next track (params: {{}})
- "spotify.search" — Search music (params: {{"query": "search terms"}})
- "spotify.now_playing" — What's playing (params: {{}})
- "youtube.play" — Play from YouTube (params: {{"query": "what to play"}})
- "youtube.search" — Search YouTube (params: {{"query": "search terms"}})
- "learning.vocab_add" — Save a word (params: {{"word": "...", "translation": "..."}})
- "learning.vocab_quiz" — Start quiz (params: {{}})
- "learning.vocab_stats" — Vocabulary stats (params: {{}})
- "learning.progress" — Learning progress (params: {{}})
- "preferences.set" — Save preference (params: {{"key": "...", "value": "..."}})
- "preferences.get" — Get preference (params: {{"key": "..."}})
- "system.volume" — Set volume (params: {{"level": 0-100}})
- "system.timer" — Set timer (params: {{"seconds": N}})
- "system.status" — Device info (params: {{}})

RULES:
1. ALWAYS include "reply" — this is what gets spoken to the user
2. Use "reply" action for normal conversation (language practice, questions, etc.)
3. Only use other actions when the user clearly requests a feature
4. Params must EXACTLY match the schema — no extra fields
5. Output ONLY valid JSON — no markdown, no explanation, no extra text
6. "reply" should be in the TARGET LANGUAGE (the language they're learning)
7. Keep replies short — this is voice, not text

LANGUAGE CONTEXT:
- Student speaks: {native_lang}
- Learning: {target_lang}
- Level: {level}

PREFERENCES:
{preferences}
"""


def build_system_prompt(
    native_lang: str,
    target_lang: str,
    level: str,
    preferences: dict[str, str] | None = None,
) -> str:
    """Build the system prompt with language and preference context."""
    pref_str = "None yet."
    if preferences:
        pref_str = "\n".join(f"- {k}: {v}" for k, v in preferences.items())

    return INTENT_SYSTEM_PROMPT.format(
        native_lang=native_lang,
        target_lang=target_lang,
        level=level,
        preferences=pref_str,
    )


def parse_intent(llm_output: str) -> Intent:
    """
    Parse LLM output into a validated Intent.

    If parsing fails, returns a safe REPLY intent with the raw text.
    The LLM can NEVER cause an action by producing malformed output.
    """
    try:
        # Strip markdown code fences if present
        text = llm_output.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        # Remove 'json' label if present
        if text.startswith("json"):
            text = text[4:].strip()

        data = json.loads(text)

        # Validate it's a dict with expected fields
        if not isinstance(data, dict):
            raise ValueError("Not a JSON object")

        # Parse action
        action_str = data.get("action", "reply")
        try:
            action = IntentType(action_str)
        except ValueError:
            logger.warning("Unknown action '%s' from LLM, falling back to reply", action_str)
            return Intent(
                action=IntentType.REPLY,
                params={},
                reply=data.get("reply", llm_output),
            )

        return Intent(
            action=action,
            params=data.get("params", {}),
            reply=data.get("reply", ""),
        )

    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning("Failed to parse intent from LLM: %s", e)
        # Safe fallback — just speak whatever the LLM said
        return Intent(
            action=IntentType.REPLY,
            params={},
            reply=llm_output,
        )
