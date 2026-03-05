"""LLM engine interface and factory."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.config import BrainConfig


class BrainEngine(ABC):
    """Abstract LLM brain."""

    @abstractmethod
    async def chat(self, messages: list[dict[str, str]]) -> str:
        """Send messages and get response."""
        ...


class OpenAIBrain(BrainEngine):
    """OpenAI-compatible brain (works with OpenAI, Ollama, etc.)."""

    def __init__(self, config: BrainConfig) -> None:
        from openai import AsyncOpenAI

        kwargs: dict = {}
        if config.api_key:
            kwargs["api_key"] = config.api_key
        if config.base_url:
            kwargs["base_url"] = config.base_url
        self.client = AsyncOpenAI(**kwargs)
        self.model = config.model
        self.temperature = config.temperature
        self.max_tokens = config.max_tokens

    async def chat(self, messages: list[dict[str, str]]) -> str:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,  # type: ignore[arg-type]
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        return response.choices[0].message.content or ""


class AnthropicBrain(BrainEngine):
    """Anthropic Claude brain."""

    def __init__(self, config: BrainConfig) -> None:
        from anthropic import AsyncAnthropic

        self.client = AsyncAnthropic(api_key=config.api_key or "")
        self.model = config.model
        self.temperature = config.temperature
        self.max_tokens = config.max_tokens

    async def chat(self, messages: list[dict[str, str]]) -> str:
        # Extract system message
        system = ""
        chat_messages = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                chat_messages.append(m)

        response = await self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=chat_messages,  # type: ignore[arg-type]
            temperature=self.temperature,
        )
        return response.content[0].text  # type: ignore[union-attr]


def create_brain(config: BrainConfig) -> BrainEngine:
    """Factory to create brain engine from config."""
    if config.provider in ("openai", "ollama"):
        return OpenAIBrain(config)
    elif config.provider == "anthropic":
        return AnthropicBrain(config)
    else:
        raise ValueError(f"Unknown brain provider: {config.provider}")
