"""Alarm words in the free text of a message (RF-85, HU-49).

A message that names a warning sign makes the app suggest calling emergency
services, and the care team is told that a message with such a word waits. The
list below is the one documented for the emergency symptom handler of the AI
module (``docs/Modulo-IA.md``, section 7), written as plain words because the
text of a message is not a catalog symptom.

Clinical validation pending: the clinical team must confirm this list before
release. Compound criteria, such as "glucosa muy baja con síntomas", are not
words and stay with the glucose alerts, not with free text.

Matching is on whole words and phrases after NFKC, case folding and removal of
accents, so "Convulsión" and "convulsion" match and "confusionada" does not
match "confusión" by accident of a substring.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from typing import Final, final

ALARM_KEYWORDS: Final[tuple[str, ...]] = (
    "confusión",
    "pérdida de conocimiento",
    "convulsión",
    "desmayo",
    "dificultad para respirar",
    "cetonas",
)
"""The alarm words, as the clinic reads them. Pending clinical validation."""

_TOKEN: Final = re.compile(r"\w+")


def _tokens(text: str) -> tuple[str, ...]:
    """Words of ``text`` in NFKC, case folded and without combining accents."""
    composed = unicodedata.normalize("NFKC", text).casefold()
    decomposed = unicodedata.normalize("NFD", composed)
    plain = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return tuple(_TOKEN.findall(plain))


@final
class AlarmKeywordDetector:
    """Finds the alarm words of a message; pure, with no I/O.

    The keywords are normalized once at construction, with the same rules as the
    text, so the list can be written with its accents.
    """

    def __init__(self, keywords: Sequence[str] = ALARM_KEYWORDS) -> None:
        entries: list[tuple[str, tuple[str, ...]]] = []
        for keyword in keywords:
            tokens = _tokens(keyword)
            if not tokens:
                raise ValueError("an alarm keyword must contain at least one word")
            entries.append((keyword, tokens))
        self._entries: tuple[tuple[str, tuple[str, ...]], ...] = tuple(entries)

    def detect(self, text: str) -> tuple[str, ...]:
        """The keywords found in ``text``, in list order, each one once.

        The answer names the keywords and never the text around them.
        """
        words = _tokens(text)
        return tuple(
            keyword
            for keyword, tokens in self._entries
            if _contains_sequence(words, tokens)
        )


def _contains_sequence(words: tuple[str, ...], phrase: tuple[str, ...]) -> bool:
    """``True`` when ``phrase`` appears as consecutive whole words of ``words``."""
    size = len(phrase)
    return any(
        words[start : start + size] == phrase for start in range(len(words) - size + 1)
    )
