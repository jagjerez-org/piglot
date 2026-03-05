"""Spotify Web API client."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import spotipy
from spotipy.oauth2 import SpotifyOAuth

if TYPE_CHECKING:
    from src.config import SpotifyConfig


class SpotifyClient:
    """Wrapper around Spotify Web API for music control."""

    def __init__(self, config: SpotifyConfig) -> None:
        self.config = config
        self.sp = spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                client_id=config.client_id,
                client_secret=config.client_secret,
                redirect_uri=config.redirect_uri,
                scope="user-modify-playback-state user-read-playback-state user-read-currently-playing",
            )
        )

    def _get_device_id(self) -> str | None:
        """Find the PiGlot Spotify Connect device."""
        devices = self.sp.devices()
        for device in devices.get("devices", []):
            if device["name"] == self.config.device_name:
                return device["id"]
        return None

    async def play_track(self, query: str) -> str:
        """Search and play a track. Returns track info string."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._play_track_sync, query)

    def _play_track_sync(self, query: str) -> str:
        results = self.sp.search(q=query, limit=1, type="track")
        tracks = results.get("tracks", {}).get("items", [])
        if not tracks:
            return f"No results found for: {query}"

        track = tracks[0]
        device_id = self._get_device_id()
        self.sp.start_playback(device_id=device_id, uris=[track["uri"]])
        return f"{track['name']} by {track['artists'][0]['name']}"

    async def play_playlist(self, query: str, language: str | None = None) -> str:
        """Search and play a playlist."""
        loop = asyncio.get_event_loop()
        search_query = f"{query} {language}" if language else query
        return await loop.run_in_executor(None, self._play_playlist_sync, search_query)

    def _play_playlist_sync(self, query: str) -> str:
        results = self.sp.search(q=query, limit=1, type="playlist")
        playlists = results.get("playlists", {}).get("items", [])
        if not playlists:
            return f"No playlist found for: {query}"

        playlist = playlists[0]
        device_id = self._get_device_id()
        self.sp.start_playback(device_id=device_id, context_uri=playlist["uri"])
        return f"Playing: {playlist['name']}"

    async def pause(self) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.sp.pause_playback)

    async def resume(self) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.sp.start_playback)

    async def skip(self) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.sp.next_track)

    async def current_track(self) -> str | None:
        """Get currently playing track info."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._current_track_sync)

    def _current_track_sync(self) -> str | None:
        current = self.sp.current_playback()
        if not current or not current.get("item"):
            return None
        item = current["item"]
        return f"{item['name']} by {item['artists'][0]['name']}"
