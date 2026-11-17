"""Language-aware text helpers. A song is Hebrew ("he") or Spanish ("es"); Hebrew-only helpers live in hebrew.py."""
import re
import unicodedata

from .hebrew import has_hebrew
from .hebrew import letters as hebrew_letters

LANGUAGES = {"he": "Hebrew", "es": "Spanish"}
SPANISH_LETTER_RE = re.compile(r"[a-záéíóúüñ]")  # matched on lower-cased NFC text


def check_language(language: str) -> str:
    if language not in LANGUAGES:
        raise ValueError(f"language must be one of {', '.join(LANGUAGES)}")
    return language


def _lower(text: str) -> str:
    return unicodedata.normalize("NFC", text).lower()


def has_lyrics_text(text: str, language: str) -> bool:
    """True when the text has letters of the song's language (a sung line, not just numbers or punctuation)."""
    return has_hebrew(text) if language == "he" else bool(SPANISH_LETTER_RE.search(_lower(text)))


def letters(text: str, language: str) -> str:
    """A word's letters, for matching word forms across songs: Hebrew letters without points; Spanish letters
    lower-cased with their accents kept ("está" and "esta" are different words), punctuation dropped."""
    return hebrew_letters(text) if language == "he" else "".join(SPANISH_LETTER_RE.findall(_lower(text)))
