"""PiGlot — AI Language Learning Assistant."""

from __future__ import annotations

import asyncio
import signal
import sys

from rich.console import Console

from src.audio.capture import AudioCapture
from src.audio.playback import AudioPlayback
from src.audio.wake_word import WakeWordDetector
from src.brain.conversation import ConversationManager
from src.brain.engine import create_brain
from src.config import load_config
from src.proxy.gateway import ProxyGateway, load_custom_services
from src.stt.engine import create_stt_engine
from src.tts.engine import create_tts_engine

console = Console()


class PiGlot:
    """Main PiGlot application."""

    def __init__(self, config_path: str = "config/config.yaml") -> None:
        self.config = load_config(config_path)
        self.running = False

        # Initialize proxy gateway (starts before everything else)
        services = load_custom_services()
        self.proxy = ProxyGateway(services=services)

        # Initialize components
        self.capture = AudioCapture(self.config.audio)
        self.playback = AudioPlayback(self.config.audio)
        self.wake_word = WakeWordDetector(self.config.piglot.wake_word)
        self.stt = create_stt_engine(self.config.stt)
        self.tts = create_tts_engine(self.config.tts, self.config.piglot.target_language)
        self.brain = create_brain(self.config.brain)
        self.conversation = ConversationManager(
            brain=self.brain,
            native_lang=self.config.piglot.language,
            target_lang=self.config.piglot.target_language,
            level=self.config.piglot.level,
        )

    async def run(self) -> None:
        """Main loop: listen → transcribe → think → speak."""
        # Start proxy gateway first
        await self.proxy.start()
        console.print("[bold blue]🛡️  Proxy gateway running on :8899[/]")

        self.running = True
        console.print("[bold green]🥧 PiGlot is ready![/]")
        console.print(
            f"   Language: {self.config.piglot.language} → {self.config.piglot.target_language}"
        )
        console.print(f"   Level: {self.config.piglot.level}")
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

                # 3. Transcribe
                console.print("[bold yellow]🧠 Thinking...[/]")
                text = await self.stt.transcribe(audio_data)
                if not text.strip():
                    continue
                console.print(f"[green]You:[/] {text}")

                # 4. Get response from brain
                response = await self.conversation.respond(text)
                console.print(f"[blue]PiGlot:[/] {response}")

                # 5. Speak response
                console.print("[bold magenta]🔊 Speaking...[/]")
                audio_response = await self.tts.synthesize(response)
                await self.playback.play(audio_response)

            except KeyboardInterrupt:
                break
            except Exception as e:
                console.print(f"[red]Error: {e}[/]")
                if sys.flags.dev_mode:
                    console.print_exception()

        console.print("\n[bold]👋 PiGlot shutting down.[/]")

    def stop(self) -> None:
        """Stop the main loop."""
        self.running = False


def main() -> None:
    """Entry point."""
    app = PiGlot()

    def handle_signal(sig: int, frame: object) -> None:
        app.stop()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    asyncio.run(app.run())


if __name__ == "__main__":
    main()
