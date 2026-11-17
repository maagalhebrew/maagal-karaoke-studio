"""Add or remove a lyric word in a saved song (the lyrics weren't perfect).

Word ids are positional (L40W3), so the rest of the line is renumbered and clips that point at those words are
moved with them. A new word gets time next to its neighbour (the gap, or half the neighbour's span) and is
flagged timing-adjusted so it gets checked.
"""
from .hebrew import normalize
from .stages import MIN_WORD_MS, _enforce_timing

GAP_MIN_MS = 300   # a gap at least this long next to the word is used for the new word
GAP_MAX_MS = 1500  # ...but not more than this of it


class WordEditError(ValueError):
    """Shown to the user as is."""


def _find(song: dict, word_id: str) -> tuple[dict, int]:
    for line in song["lines"]:
        for k, w in enumerate(line["words"]):
            if w["id"] == word_id:
                return line, k
    raise WordEditError(f"no word {word_id}")


def _renumber(song: dict, line: dict) -> dict[str, str]:
    """Give the line's words ids in order again; returns old id -> new id for the words that moved."""
    moved = {}
    for k, w in enumerate(line["words"], 1):
        new = f"{line['id']}W{k}"
        if w["id"] != new:
            moved[w["id"]] = new
        w["id"] = new
    for clip in song["clips"]:
        clip["fromWord"] = moved.get(clip["fromWord"], clip["fromWord"])
        clip["toWord"] = moved.get(clip["toWord"], clip["toWord"])
    return moved


def insert_word(song: dict, word_id: str, side: str, text: str,
                start_ms: int | None = None, end_ms: int | None = None) -> str:
    """Insert `text` (one word, as written) before/after word_id. Returns the new word's id.
    With start_ms/end_ms (a word Whisper heard) it goes exactly there, trimming neighbours that overlap it."""
    text = normalize(text.strip())
    if not text or len(text.split()) != 1:
        raise WordEditError("type one word (no spaces)")
    if side not in ("before", "after"):
        raise WordEditError("side must be before or after")
    line, k = _find(song, word_id)
    words = [w for l in song["lines"] for w in l["words"]]
    i = words.index(line["words"][k])
    anchor = words[i]
    if start_ms is not None and end_ms is not None:
        start, end = int(start_ms), max(int(end_ms), int(start_ms) + MIN_WORD_MS)
        before, after = (words[:i + 1], words[i + 1:]) if side == "after" else (words[:i], words[i:])
        for w in before:  # the forced alignment often stretched a neighbour over the missing word's time
            if w["endMs"] > start:
                w["endMs"] = max(w["startMs"] + MIN_WORD_MS, start)
        for w in after:
            if w["startMs"] < end:
                w["startMs"] = min(w["endMs"] - MIN_WORD_MS, end)
    elif side == "after":
        nxt = words[i + 1]["startMs"] if i + 1 < len(words) else song["song"]["durationMs"]
        if nxt - anchor["endMs"] >= GAP_MIN_MS:
            start, end = anchor["endMs"], min(nxt, anchor["endMs"] + GAP_MAX_MS)
        else:
            mid = (anchor["startMs"] + anchor["endMs"]) // 2
            start, end, anchor["endMs"] = mid, anchor["endMs"], mid
    else:
        prev = words[i - 1]["endMs"] if i > 0 else 0
        if anchor["startMs"] - prev >= GAP_MIN_MS:
            start, end = max(prev, anchor["startMs"] - GAP_MAX_MS), anchor["startMs"]
        else:
            mid = (anchor["startMs"] + anchor["endMs"]) // 2
            start, end, anchor["startMs"] = anchor["startMs"], mid, mid

    flags = [] if start_ms is not None else ["timing-adjusted"]  # Whisper's timing is good; a guess isn't
    new = {"id": "new", "plain": text, "startMs": start, "endMs": end, "confidence": 0.0, "flags": flags}
    line["words"].insert(k + (side == "after"), new)
    _renumber(song, line)
    _enforce_timing([w for l in song["lines"] for w in l["words"]], song["song"]["durationMs"])
    return new["id"]


def delete_word(song: dict, word_id: str) -> str | None:
    """Remove word_id. Clips that start/end on it move to the neighbouring word. Returns the id of a
    neighbouring word to select next."""
    line, k = _find(song, word_id)
    if len(line["words"]) == 1:
        raise WordEditError("that is the line's only word: delete the line instead")
    words = [w["id"] for l in song["lines"] for w in l["words"]]
    i = words.index(word_id)
    for clip in song["clips"]:
        if clip["fromWord"] == word_id and clip["toWord"] == word_id:
            raise WordEditError(f"clip {clip['id']} ({clip['name']}) is just this word: delete the clip first")
        if clip["fromWord"] == word_id:
            clip["fromWord"] = words[i + 1]
        if clip["toWord"] == word_id:
            clip["toWord"] = words[i - 1]
    del line["words"][k]
    _renumber(song, line)
    return line["words"][min(k, len(line["words"]) - 1)]["id"]
