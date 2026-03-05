"""Learning progress tracker."""

from __future__ import annotations

import json
from datetime import datetime, date
from pathlib import Path
from typing import Any


class ProgressTracker:
    """Track learning sessions and progress."""

    def __init__(self, progress_file: str = "data/progress.json") -> None:
        self.path = Path(progress_file)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {
            "total_minutes": 0,
            "total_sessions": 0,
            "streak_days": 0,
            "last_session_date": None,
            "daily_log": {},
            "words_learned": 0,
        }

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2, default=str))

    def start_session(self) -> None:
        """Record session start."""
        today = date.today().isoformat()
        last = self.data.get("last_session_date")

        if last == today:
            pass  # Already tracked today
        elif last == (date.today().toordinal() - 1):
            self.data["streak_days"] += 1
        else:
            self.data["streak_days"] = 1

        self.data["last_session_date"] = today
        self.data["total_sessions"] += 1
        self._save()

    def add_minutes(self, minutes: float) -> None:
        """Add practice minutes."""
        today = date.today().isoformat()
        self.data["total_minutes"] += minutes
        daily = self.data.setdefault("daily_log", {})
        daily[today] = daily.get(today, 0) + minutes
        self._save()

    def add_words(self, count: int = 1) -> None:
        """Track new words learned."""
        self.data["words_learned"] = self.data.get("words_learned", 0) + count
        self._save()

    def get_summary(self) -> str:
        """Get a spoken summary of progress."""
        return (
            f"You've practiced for {self.data['total_minutes']:.0f} minutes "
            f"across {self.data['total_sessions']} sessions. "
            f"Current streak: {self.data['streak_days']} days. "
            f"Words learned: {self.data.get('words_learned', 0)}."
        )
