"""Physical button support (optional)."""

from __future__ import annotations

import asyncio
from typing import Callable


class ButtonHandler:
    """Handle physical button press as alternative to wake word."""

    def __init__(self, pin: int | None = None) -> None:
        self.pin = pin
        self.enabled = pin is not None
        self._gpio = None

    def setup(self) -> None:
        if not self.enabled:
            return
        try:
            import RPi.GPIO as GPIO
            self._gpio = GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        except (ImportError, RuntimeError):
            self.enabled = False

    async def wait_for_press(self) -> bool:
        """Wait for button press. Returns True when pressed."""
        if not self.enabled or self._gpio is None:
            return False

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._wait_sync)

    def _wait_sync(self) -> bool:
        if self._gpio is None:
            return False
        channel = self._gpio.wait_for_edge(self.pin, self._gpio.FALLING, timeout=5000)
        return channel is not None

    def cleanup(self) -> None:
        if self._gpio:
            self._gpio.cleanup()
