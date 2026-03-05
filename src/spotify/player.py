"""High-level Spotify player for PiGlot."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.spotify.client import SpotifyClient

if TYPE_CHECKING:
    from src.config import SpotifyConfig


class SpotifyPlayer:
    """High-level Spotify controls for the language tutor."""

    def __init__(self, config: SpotifyConfig) -> None:
        self.enabled = config.enabled
        self.client = SpotifyClient(config) if config.enabled else None

    async def handle_command(self, command: str, language: str | None = None) -> str:
        """Handle a Spotify-related voice command."""
        if not self.enabled or not self.client:
            return "Spotify is not configured. Add your credentials to config.yaml."

        cmd = command.lower().strip()

        if cmd in ("pause", "stop", "para"):
            await self.client.pause()
            return "Paused."
        elif cmd in ("resume", "play", "continua"):
            await self.client.resume()
            return "Resuming playback."
        elif cmd in ("skip", "next", "siguiente"):
            await self.client.skip()
            return "Skipping to next track."
        elif cmd.startswith("play ") or cmd.startswith("pon "):
            query = cmd.split(" ", 1)[1]
            return await self.client.play_track(query)
        elif "playlist" in cmd:
            query = cmd.replace("playlist", "").strip()
            return await self.client.play_playlist(query, language)
        elif cmd in ("what's playing", "qué suena"):
            track = await self.client.current_track()
            return track or "Nothing is playing right now."
        else:
            # Try as a search query
            return await self.client.play_track(cmd)
