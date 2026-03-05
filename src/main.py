"""PiGlot — AI Language Learning Assistant (Device-side)."""

from __future__ import annotations

import asyncio
import signal
import sys

from rich.console import Console

from src.audio.capture import AudioCapture
from src.audio.playback import AudioPlayback
from src.audio.wake_word import WakeWordDetector
from src.config import load_config
from src.gateway.client import GatewayClient
from src.tts.engine import DEFAULT_VOICES

console = Console()


class PiGlot:
    """
    Main PiGlot application (runs on Raspberry Pi).

    In gateway mode (production):
      - Captures audio → sends to gateway → speaks reply
      - Zero API keys, zero LLM, zero external calls
      - The gateway handles EVERYTHING

    In local mode (development):
      - Runs LLM + STT + TTS locally
    """

    def __init__(self, config_path: str = "config/config.yaml") -> None:
        self.config = load_config(config_path)
        self.running = False

        # Audio (always local)
        self.capture = AudioCapture(self.config.audio)
        self.playback = AudioPlayback(self.config.audio)
        self.wake_word = WakeWordDetector(self.config.piglot.wake_word)

        # Gateway client
        if self.config.gateway.enabled:
            self.gateway = GatewayClient(
                gateway_url=self.config.gateway.url,
                device_token=self.config.gateway.device_token,
            )
        else:
            self.gateway = None

        # Conversation history (sent to gateway for context)
        self.history: list[dict[str, str]] = []

    async def run(self) -> None:
        """Main loop: listen → gateway → speak."""
        self.running = True

        if self.gateway:
            console.print("[bold blue]🌐 Gateway mode[/]")
            console.print(f"   Gateway: {self.config.gateway.url}")
            # Verify connection
            try:
                status = await self.gateway.status()
                console.print(f"   Device: {status.get('name', 'unknown')}")
                console.print(f"   Plan: {status.get('plan', 'unknown')}")
                console.print(f"   Requests today: {status.get('requests_today', 0)}/{status.get('daily_limit', 0)}")
            except Exception as e:
                console.print(f"[red]⚠️  Gateway unreachable: {e}[/]")
                return
        else:
            console.print("[bold yellow]⚠️  Local mode (no gateway)[/]")
            console.print("   Set gateway.enabled=true in config for production")

        console.print()
        console.print("[bold green]🥧 PiGlot is ready![/]")
        console.print(f'   Wake word: "{self.config.piglot.wake_word}"')
        console.print("   Say the wake word to start talking...\n")

        while self.running:
            try:
                # 1. Wait for wake word
                console.print("[dim]Listening for wake word...[/]", end="\r")
                detected = await self.wake_word.listen(self.capture)
                if not detected:
                    continue

                console.print("[bold cyan]🎤 Listening...[/]")

                # 2. Capture speech
                audio_data = await self.capture.record_until_silence()
                if audio_data is None:
                    console.print("[dim]No speech detected.[/]")
                    continue

                # 3. Process through gateway
                if self.gateway:
                    result = await self._process_gateway(audio_data)
                else:
                    result = await self._process_local(audio_data)

                if result is None:
                    continue

                reply_text, audio_reply = result

                # 4. Speak
                if audio_reply:
                    console.print("[bold magenta]🔊 Speaking...[/]")
                    await self.playback.play(audio_reply)

            except KeyboardInterrupt:
                break
            except Exception as e:
                console.print(f"[red]Error: {e}[/]")
                if sys.flags.dev_mode:
                    console.print_exception()

        if self.gateway:
            await self.gateway.close()
        console.print("\n[bold]👋 PiGlot shutting down.[/]")

    async def _process_gateway(self, audio_data) -> tuple[str, bytes] | None:
        """Full pipeline through gateway."""
        import soundfile as sf
        import io
        import numpy as np

        # Convert to WAV bytes
        buf = io.BytesIO()
        sf.write(buf, audio_data, 16000, format="WAV")
        audio_bytes = buf.getvalue()

        # 1. Transcribe via gateway
        console.print("[bold yellow]🧠 Transcribing...[/]")
        text = await self.gateway.transcribe(audio_bytes)
        if not text.strip():
            return None
        console.print(f"[green]You:[/] {text}")

        # 2. Send turn to gateway (LLM + intent execution happens there)
        console.print("[bold yellow]🧠 Thinking...[/]")
        turn = await self.gateway.turn(text, self.history)

        # Update local history
        self.history.append({"role": "user", "content": text})
        self.history.append({"role": "assistant", "content": turn.reply})
        # Keep history bounded
        if len(self.history) > 40:
            self.history = self.history[-40:]

        console.print(f"[blue]PiGlot:[/] {turn.reply}")

        # Log intent if it wasn't just a reply
        if turn.action != "reply":
            status = "✅" if turn.executed else "❌"
            console.print(f"[dim]  {status} {turn.action} {turn.data or turn.error or ''}[/]")

        # 3. Synthesize speech via gateway
        voice = DEFAULT_VOICES.get(self.config.piglot.target_language, "en-US-AriaNeural")
        audio = await self.gateway.synthesize(turn.reply, voice=voice)

        return turn.reply, audio

    async def _process_local(self, audio_data) -> tuple[str, bytes] | None:
        """Local pipeline (development only)."""
        from src.stt.engine import create_stt_engine
        from src.tts.engine import create_tts_engine
        from src.brain.engine import create_brain
        from src.brain.conversation import ConversationManager

        # Lazy init local components
        if not hasattr(self, "_local_stt"):
            self._local_stt = create_stt_engine(self.config.stt)
            self._local_tts = create_tts_engine(self.config.tts, self.config.piglot.target_language)
            brain = create_brain(self.config.brain)
            self._local_conv = ConversationManager(
                brain=brain,
                native_lang=self.config.piglot.language,
                target_lang=self.config.piglot.target_language,
                level=self.config.piglot.level,
            )

        console.print("[bold yellow]🧠 Thinking...[/]")
        text = await self._local_stt.transcribe(audio_data)
        if not text.strip():
            return None
        console.print(f"[green]You:[/] {text}")

        response = await self._local_conv.respond(text)
        console.print(f"[blue]PiGlot:[/] {response}")

        audio = await self._local_tts.synthesize(response)
        return response, audio

    def stop(self) -> None:
        self.running = False


def main() -> None:
    app = PiGlot()

    def handle_signal(sig: int, frame: object) -> None:
        app.stop()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    asyncio.run(app.run())


if __name__ == "__main__":
    main()
