"""Exercise generators for language practice."""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.learning.vocabulary import VocabularyDB


class ExerciseGenerator:
    """Generate language exercises from vocabulary."""

    def __init__(self, vocab: VocabularyDB) -> None:
        self.vocab = vocab

    def translation_quiz(self) -> str | None:
        """Generate a translation quiz prompt."""
        word = self.vocab.get_random_word()
        if not word:
            return None

        if random.random() > 0.5:
            return f"How do you say '{word['translation']}' in the target language?"
        else:
            return f"What does '{word['word']}' mean?"

    def fill_in_blank(self) -> str | None:
        """Generate a fill-in-the-blank exercise."""
        word = self.vocab.get_random_word()
        if not word or not word.get("context"):
            return None

        context = word["context"]
        blanked = context.replace(word["word"], "____")
        return f"Fill in the blank: {blanked}"

    def review_session(self, count: int = 5) -> list[dict]:
        """Get a set of words for a review session."""
        due = self.vocab.get_due_words(limit=count)
        exercises = []
        for word in due:
            exercises.append({
                "word": word["word"],
                "translation": word["translation"],
                "type": random.choice(["translate", "define", "use_in_sentence"]),
            })
        return exercises
