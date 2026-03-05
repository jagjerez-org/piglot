"""LED feedback control (optional NeoPixel/WS2812)."""

from __future__ import annotations

from enum import Enum


class State(Enum):
    IDLE = "idle"           # Dim blue pulse
    LISTENING = "listening" # Bright green
    THINKING = "thinking"   # Yellow pulse
    SPEAKING = "speaking"   # Cyan
    ERROR = "error"         # Red flash


class LEDController:
    """Control status LEDs for visual feedback."""

    def __init__(self, pin: int | None = None, count: int = 12) -> None:
        self.pin = pin
        self.count = count
        self._strip = None
        self.enabled = pin is not None

    def _init_strip(self) -> None:
        if self._strip is None and self.enabled:
            try:
                from rpi_ws281x import PixelStrip, Color
                self._strip = PixelStrip(self.count, self.pin, 800000, 10, False, 50, 0)
                self._strip.begin()
            except (ImportError, RuntimeError):
                self.enabled = False

    def set_state(self, state: State) -> None:
        """Set LED state."""
        if not self.enabled:
            return
        self._init_strip()
        if self._strip is None:
            return

        from rpi_ws281x import Color

        colors = {
            State.IDLE: Color(0, 0, 30),
            State.LISTENING: Color(0, 255, 0),
            State.THINKING: Color(255, 200, 0),
            State.SPEAKING: Color(0, 200, 255),
            State.ERROR: Color(255, 0, 0),
        }
        color = colors.get(state, Color(0, 0, 0))
        for i in range(self.count):
            self._strip.setPixelColor(i, color)
        self._strip.show()

    def off(self) -> None:
        """Turn off all LEDs."""
        if not self.enabled or self._strip is None:
            return
        from rpi_ws281x import Color
        for i in range(self.count):
            self._strip.setPixelColor(i, Color(0, 0, 0))
        self._strip.show()
