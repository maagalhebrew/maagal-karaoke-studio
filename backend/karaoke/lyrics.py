"""Parse lyrics: one sung line per line, blank line between sections, optional [labels].
A known section word alone on its line ("Chorus", "פזמון x2", "(בית)") is a label too, not a sung line.

Also reads lyrics with each line followed by its English translation (the ChatGPT lyrics-skill format; older files
add a pronunciation line, read but no longer used). In that format blank lines only separate the blocks, so
sections come from [labels] alone. Hebrew tells its English lines apart by alphabet, so the format is detected;
Spanish and English share one, so for Spanish the caller says whether English lines are there, and lines then
alternate lyric, English (a blank line or label starts again with a lyric line).
"""
import re
from dataclasses import dataclass, field

from .hebrew import has_hebrew
from .text import has_lyrics_text

LABEL_RE = re.compile(r"^\[(.+)\]$")
REPEAT_RE = re.compile(r"\s*(?:[x×]\s*\d+|\d+\s*[x×])$", re.IGNORECASE)  # "x2", "×2", "2x"
MARKDOWN_RE = re.compile(r"^(?:[-*•]\s+|\d+[.)]\s+)|[*_`]")  # bullets, numbering, bold/italics from chat output
KINDS = {
    "verse": "verse", "chorus": "chorus", "bridge": "bridge", "intro": "intro",
    "outro": "outro", "transition": "transition",
    "בית": "verse", "פזמון": "chorus", "גשר": "bridge", "פתיחה": "intro", "סיום": "outro",
    "verso": "verse", "estrofa": "verse", "coro": "chorus", "estribillo": "chorus", "puente": "bridge",
    "interludio": "transition",
}


@dataclass
class Section:
    kind: str = "verse"
    label: str | None = None  # None = numbered automatically ("Verse 2")
    lines: list[list[str]] = field(default_factory=list)  # each line = list of word tokens
    english: list[str] = field(default_factory=list)  # per line ("" when not given)
    pronunciation: list[str] = field(default_factory=list)  # per line, ChatGPT style ("" when not given)


def _words(line: str) -> list[str]:
    return [w for w in line.split() if any(ch.isalnum() for ch in w)]


def _section_kind(name: str) -> str | None:
    """The section kind a label names ("Chorus 2", "פזמון x2", "Verse:"), or None."""
    key = REPEAT_RE.sub("", name.strip().rstrip(":").strip())
    return KINDS.get(key.lower().rstrip(" 0123456789"))


def _label(line: str) -> tuple[str, str | None] | None:
    """(kind, custom label or None) when the line is a section label: anything in [brackets], or a known
    section word on its own, optionally in (parentheses). None for a sung line."""
    m = LABEL_RE.match(line)
    if m:
        name = m.group(1).strip()
        kind = _section_kind(name) or "custom"
        return kind, (name if kind == "custom" else None)
    bare = line[1:-1] if line.startswith("(") and line.endswith(")") else line
    kind = _section_kind(bare) if bare else None
    return (kind, None) if kind else None


def _clean(raw: str) -> str:
    return MARKDOWN_RE.sub("", raw.strip()).strip()


def is_three_line(lines: list[str]) -> bool:
    """True when Hebrew lines are followed by non-Hebrew lines (translation / pronunciation)."""
    content = [ln for ln in lines if ln and not _label(ln)]
    return any(has_hebrew(a) and not has_hebrew(b) for a, b in zip(content, content[1:]))


def parse(text: str, language: str = "he", english_lines: bool | None = None) -> list[Section]:
    """english_lines: True = each lyric line is followed by its English; False = lyrics only;
    None = detect (Hebrew only; Spanish lyrics are taken as lyrics only)."""
    raw_lines = [_clean(r) for r in text.lstrip("\ufeff").splitlines()]
    three = (is_three_line(raw_lines) if language == "he" else False) if english_lines is None else english_lines
    sections: list[Section] = []
    current = Section()
    extras = 0  # English (and pronunciation) lines attached to the current lyric line
    expect_lyric = True  # Spanish with English lines: the next content line is a lyric line

    def close():
        nonlocal current
        if current.lines:
            sections.append(current)

    for line in raw_lines:
        label = _label(line)
        if label:
            close()
            current = Section(kind=label[0], label=label[1])
            extras, expect_lyric = 2, True
            continue
        if not line:
            if not three:
                close()
                current = Section()
            expect_lyric = True
            continue
        words = _words(line)
        if not words:
            continue
        extra = not has_hebrew(line) if language == "he" else not expect_lyric
        if three and extra:
            if current.lines and extras < 2:  # 1st = English, 2nd = pronunciation; anything more is ignored
                (current.english if extras == 0 else current.pronunciation)[-1] = line
                extras += 1
            expect_lyric = True
            continue
        current.lines.append(words)
        current.english.append("")
        current.pronunciation.append("")
        extras, expect_lyric = 0, False
    close()

    counts: dict[str, int] = {}
    for s in sections:
        if s.label is None:
            counts[s.kind] = counts.get(s.kind, 0) + 1
            s.label = f"{s.kind.capitalize()} {counts[s.kind]}"
    return sections


def lyric_line_count(sections: list[Section], language: str = "he") -> int:
    """Lines with letters of the song's language."""
    return sum(has_lyrics_text(" ".join(line), language) for s in sections for line in s.lines)


def summary(sections: list[Section], language: str = "he") -> dict:
    """Counts only (rule 5): what the import page shows before processing."""
    lines = [(s, i) for s in sections for i in range(len(s.lines))]
    return {"sections": len(sections), "lines": len(lines), "lyricLines": lyric_line_count(sections, language),
            "words": sum(len(s.lines[i]) for s, i in lines),
            "withEnglish": sum(bool(s.english[i]) for s, i in lines),
            "withPronunciation": sum(bool(s.pronunciation[i]) for s, i in lines),
            "sectionLabels": [s.label for s in sections]}
