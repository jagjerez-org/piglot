"""Conversation state management."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.brain.prompts import get_tutor_prompt

if TYPE_CHECKING:
    from src.brain.engine import BrainEngine


class ConversationManager:
    """Manages conversation history and context."""

    MAX_HISTORY = 20  # Keep last N exchanges to manage token usage

    def __init__(
        self,
        brain: BrainEngine,
        native_lang: str,
        target_lang: str,
        level: str,
    ) -> None:
        self.brain = brain
        self.system_prompt = get_tutor_prompt(native_lang, target_lang, level)
        self.history: list[dict[str, str]] = []

    async def respond(self, user_text: str) -> str:
        """Process user input and return assistant response."""
        self.history.append({"role": "user", "content": user_text})

        # Trim history if too long
        if len(self.history) > self.MAX_HISTORY * 2:
            self.history = self.history[-self.MAX_HISTORY * 2 :]

        messages = [
            {"role": "system", "content": self.system_prompt},
            *self.history,
        ]

        response = await self.brain.chat(messages)
        self.history.append({"role": "assistant", "content": response})
        return response

    def reset(self) -> None:
        """Clear conversation history."""
        self.history.clear()
