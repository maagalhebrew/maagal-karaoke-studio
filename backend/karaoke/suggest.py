"""Missing / extra word suggestions: the lyrics compared with what Whisper heard (heard.json, saved by the align
stage or `transcribe_song`). Whisper mishears about one word in six on songs, so these are suggestions for the
user to accept or dismiss, never automatic changes. Text stays on this machine (rule 5: never printed).
"""
import difflib
import json
from pathlib import Path

from .stages import _key

NEAR_MS = 400  # a heard word this close to the gap between two lyric words counts as being in that gap


def load_heard(folder: Path) -> list | None:
    path = folder / "heard.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def load_dismissed(folder: Path) -> set[str]:
    path = folder / "suggestions-dismissed.json"
    return set(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else set()


def dismiss(folder: Path, key: str) -> None:
    keys = load_dismissed(folder) | {key}
    (folder / "suggestions-dismissed.json").write_text(json.dumps(sorted(keys), ensure_ascii=False), encoding="utf-8")


def remap_dismissed(folder: Path, word_map: dict[str, str], removed: list[str] = ()) -> None:
    """Keep dismissed suggestions dismissed after word ids change (keys are type:wordId:side:text). Keys on
    removed words are dropped, so their old ids can't land on whichever word has that id now."""
    keys = load_dismissed(folder)
    if not keys:
        return
    moved = set()
    for key in keys:
        kind, word_id, rest = key.split(":", 2) if key.count(":") >= 2 else (key, "", "")
        if word_id in removed:
            continue
        moved.add(f"{kind}:{word_map.get(word_id, word_id)}:{rest}" if word_id else key)
    (folder / "suggestions-dismissed.json").write_text(json.dumps(sorted(moved), ensure_ascii=False), encoding="utf-8")


def suggestions(song: dict, heard: list, dismissed: set[str] = frozenset()) -> list[dict]:
    """[{"key", "type": "missing"|"unheard", "lineId", "wordId", "side"?, "text", "startMs", "endMs"}], in song order.
    missing: Whisper heard a word between two lyric words where the lyrics have none (insert it at wordId/side).
    unheard: a lyric word where Whisper heard nothing at all (maybe not sung)."""
    if not heard:
        return []
    words = [(line["id"], w) for line in song["lines"] for w in line["words"]]
    first_heard, last_heard = heard[0][1], heard[-1][2]
    matcher = difflib.SequenceMatcher(a=[_key(w["plain"]) for _, w in words], b=[h[0] for h in heard], autojunk=False)
    out = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "insert":
            prev = words[i1 - 1] if i1 > 0 else None
            nxt = words[i1] if i1 < len(words) else None
            lo = prev[1]["endMs"] - NEAR_MS if prev else 0
            hi = nxt[1]["startMs"] + NEAR_MS if nxt else song["song"]["durationMs"]
            for _, start, end, text in heard[j1:j2]:
                mid = (start + end) // 2
                if not lo <= mid <= hi:
                    continue  # heard somewhere else in time: the sequences only line up by chance
                # Attach to the nearer neighbour, so a word at the start of a line joins that line.
                if prev and (not nxt or mid - prev[1]["endMs"] <= nxt[1]["startMs"] - mid):
                    line_id, anchor, side = prev[0], prev[1], "after"
                else:
                    line_id, anchor, side = nxt[0], nxt[1], "before"
                out.append({"type": "missing", "lineId": line_id, "wordId": anchor["id"], "side": side,
                            "text": text, "startMs": start, "endMs": end})
        elif tag == "delete":
            for line_id, w in words[i1:i2]:
                if not (first_heard <= w["startMs"] and w["endMs"] <= last_heard):
                    continue  # before the first / after the last heard word Whisper often just missed quiet singing
                if any(h[1] < w["endMs"] and h[2] > w["startMs"] for h in heard):
                    continue  # something was heard there: more likely misheard than not sung
                out.append({"type": "unheard", "lineId": line_id, "wordId": w["id"], "text": w["plain"],
                            "startMs": w["startMs"], "endMs": w["endMs"]})
    for s in out:
        s["key"] = f"{s['type']}:{s['wordId']}:{s.get('side', '')}:{s['text']}"
    return [s for s in out if s["key"] not in dismissed]
