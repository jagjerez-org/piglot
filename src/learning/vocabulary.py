"""Vocabulary database with spaced repetition."""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


class VocabularyDB:
    """Simple JSON-based vocabulary with spaced repetition scoring."""

    def __init__(self, db_path: str = "data/vocabulary.db") -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.words: list[dict[str, Any]] = self._load()

    def _load(self) -> list[dict[str, Any]]:
        if self.path.exists():
            return json.loads(self.path.read_text())
        return []

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.words, indent=2, default=str))

    def add_word(
        self, word: str, translation: str, context: str = ""
    ) -> None:
        """Add a new word to the vocabulary."""
        # Check for duplicates
        for w in self.words:
            if w["word"].lower() == word.lower():
                return

        self.words.append({
            "word": word,
            "translation": translation,
            "context": context,
            "added": datetime.now().isoformat(),
            "last_reviewed": None,
            "review_count": 0,
            "score": 0,  # 0-5, higher = better known
            "next_review": datetime.now().isoformat(),
        })
        self._save()

    def get_due_words(self, limit: int = 5) -> list[dict[str, Any]]:
        """Get words due for review (spaced repetition)."""
        now = datetime.now()
        due = [
            w for w in self.words
            if w["next_review"] is None
            or datetime.fromisoformat(w["next_review"]) <= now
        ]
        # Prioritize low-score words
        due.sort(key=lambda w: w["score"])
        return due[:limit]

    def review_word(self, word: str, correct: bool) -> None:
        """Update word after review."""
        for w in self.words:
            if w["word"].lower() == word.lower():
                w["review_count"] += 1
                w["last_reviewed"] = datetime.now().isoformat()
                if correct:
                    w["score"] = min(5, w["score"] + 1)
                else:
                    w["score"] = max(0, w["score"] - 1)
                # Spaced repetition: interval grows with score
                days = 2 ** w["score"]  # 1, 2, 4, 8, 16, 32 days
                w["next_review"] = (datetime.now() + timedelta(days=days)).isoformat()
                break
        self._save()

    def get_random_word(self) -> dict[str, Any] | None:
        """Get a random word for quick quiz."""
        return random.choice(self.words) if self.words else None

    def get_stats(self) -> str:
        """Get vocabulary stats as spoken text."""
        total = len(self.words)
        mastered = sum(1 for w in self.words if w["score"] >= 4)
        learning = sum(1 for w in self.words if 0 < w["score"] < 4)
        new = sum(1 for w in self.words if w["score"] == 0)
        return (
            f"You have {total} words in your vocabulary. "
            f"{mastered} mastered, {learning} in progress, {new} new."
        )
