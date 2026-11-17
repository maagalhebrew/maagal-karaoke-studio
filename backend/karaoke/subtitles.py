"""Subtitles: one SRT per tier (lyrics, English) and one styled ASS with both, the lyrics filling word by word.

Cue windows match the caption overlay (render/src/Overlay.tsx): a line shows from LEAD_MS before its
first word to TAIL_MS after its last word, cut short where the next line begins.
"""
from .hebrew import strip_niqqud

LEAD_MS, TAIL_MS = 300, 500
RLM = "‏"  # keeps punctuation on the correct side of right-to-left lines in subtitle players
SAFE_X, SAFE_Y = 96, 54  # 5% title-safe margins at 1920x1080


def cues(song: dict, from_ms: int, to_ms: int) -> list[tuple[dict, int, int]]:
    """(line, start, end) with times relative to from_ms, only for lines visible inside the range."""
    lines = song["lines"]
    out = []
    for i, line in enumerate(lines):
        start = line["words"][0]["startMs"] - LEAD_MS
        end = line["words"][-1]["endMs"] + TAIL_MS
        if i + 1 < len(lines):
            end = min(end, lines[i + 1]["words"][0]["startMs"] - LEAD_MS)
        start, end = max(start, from_ms, 0), min(end, to_ms)
        if end > start:
            out.append((line, start - from_ms, end - from_ms))
    return out


def _rtl(song: dict) -> bool:
    return song["song"].get("language", "he") == "he"


def word_text(w: dict, show_niqqud: bool = True) -> str:
    """A word as written, or without its vowel points."""
    return w["plain"] if show_niqqud else strip_niqqud(w["plain"])


def tier_text(song: dict, line: dict, tier: str, show_niqqud: bool = True) -> str:
    if tier == "lyrics":
        text = " ".join(word_text(w, show_niqqud) for w in line["words"])
        return RLM + text + RLM if _rtl(song) else text
    return line["english"].strip()


def srt_time(ms: int) -> str:
    h, rem = divmod(int(ms), 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms_ = divmod(rem, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms_:03}"


def srt(song: dict, tier: str, from_ms: int, to_ms: int, show_niqqud: bool = True) -> str:
    blocks = []
    for line, start, end in cues(song, from_ms, to_ms):
        text = tier_text(song, line, tier, show_niqqud)
        if text.strip(RLM).strip():
            blocks.append(f"{len(blocks) + 1}\n{srt_time(start)} --> {srt_time(end)}\n{text}\n")
    return "\n".join(blocks)


# --- ASS ----------------------------------------------------------------------------
def _ass_time(ms: int) -> str:
    cs = round(ms / 10)
    h, rem = divmod(cs, 360_000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02}:{s:02}.{c:02}"


def _ass_color(hex_rgb: str, alpha: int = 0) -> str:
    r, g, b = (int(hex_rgb.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def _karaoke(song: dict, line: dict, cue_start_abs: int, show_niqqud: bool) -> str:
    """The lyrics with \\kf fills: each word fills over its own span, as in the editor's captions;
    pauses between words are plain \\k waits."""
    parts, cursor_cs = [], round(cue_start_abs / 10)
    for n, w in enumerate(line["words"]):
        start_cs, end_cs = round(w["startMs"] / 10), round(w["endMs"] / 10)
        if start_cs > cursor_cs:
            parts.append(f"{{\\k{start_cs - cursor_cs}}}")
        parts.append(f"{{\\kf{max(end_cs - max(start_cs, cursor_cs), 0)}}}{word_text(w, show_niqqud)}")
        cursor_cs = max(end_cs, cursor_cs)
        if n < len(line["words"]) - 1:
            parts.append(" ")
    text = "".join(parts)
    return RLM + text + RLM if _rtl(song) else text


def ass(song: dict, style: dict, from_ms: int, to_ms: int) -> str:
    he = style["heSizePx"]  # the lyrics line (named when it was always Hebrew)
    en = round(he * style["enScale"])
    text, hl = _ass_color(style["textColor"]), _ass_color(style["highlightColor"])
    box = style["boxOpacity"] > 0
    back = _ass_color("#000000", round((1 - style["boxOpacity"]) * 255))
    border = "3,0,0" if box else "1,3,0"  # BorderStyle 3 = box behind text; 1 = outline
    bottom = style["verticalPosition"] >= 0.5
    align = 2 if bottom else 8

    # Stack the tiers inside the title-safe area: lyrics, then English (top to bottom).
    sizes = [("Lyrics", he), ("En", en)]
    gap = round(he * 0.35)
    margins, y = {}, SAFE_Y
    for name, size in (reversed(sizes) if bottom else sizes):
        margins[name] = y
        y += round(size * 1.25) + gap

    def style_line(name, size, primary, secondary, bold):
        return (f"Style: {name},Heebo,{size},{primary},{secondary},&H00000000,{back},{bold},0,0,0,100,100,0,0,"
                f"{border},{align},{SAFE_X},{SAFE_X},{margins[name]},177")

    head = "\n".join([
        "[Script Info]", "; Karaoke Studio", "ScriptType: v4.00+", "PlayResX: 1920", "PlayResY: 1080",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, "
        "MarginV, Encoding",
        style_line("Lyrics", he, hl, text, -1),  # karaoke: fills from SecondaryColour to PrimaryColour
        style_line("En", en, text, text, 0),
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ])
    events = []
    for line, start, end in cues(song, from_ms, to_ms):
        t0, t1 = _ass_time(start), _ass_time(end)
        events.append(f"Dialogue: 0,{t0},{t1},Lyrics,,0,0,0,,{_karaoke(song, line, start + from_ms, style['showNiqqud'])}")
        if line["english"].strip():
            events.append(f"Dialogue: 0,{t0},{t1},En,,0,0,0,,{line['english'].strip()}")
    return head + "\n" + "\n".join(events) + "\n"
