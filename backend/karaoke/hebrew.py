"""Hebrew Unicode helpers."""
import re
import unicodedata

# Points (niqqud), dagesh, shin/sin dots, meteg, rafe, qamats qatan.
NIQQUD_RE = re.compile(r"[ְ-ׇֽֿׁׂׅׄ]")
CANTILLATION_RE = re.compile(r"[֑-֯]")
VOWEL_RE = re.compile(r"[ְ-ׇֻ]")  # vowel points only (incl. shva)
LETTER_RE = re.compile(r"[א-ת]")


def normalize(text: str) -> str:
    """NFC, no cantillation, no meteg — the form used for comparison and override keys."""
    text = unicodedata.normalize("NFC", text)
    text = CANTILLATION_RE.sub("", text)
    return text.replace("ֽ", "")


def strip_niqqud(text: str) -> str:
    return NIQQUD_RE.sub("", normalize(text))


def has_hebrew(text: str) -> bool:
    return bool(LETTER_RE.search(text))


def has_vowels(text: str) -> bool:
    return bool(VOWEL_RE.search(text))


def letters(text: str) -> str:
    """Hebrew letters only — used to match words across plain, pointed and aligned text."""
    return "".join(LETTER_RE.findall(strip_niqqud(text)))
