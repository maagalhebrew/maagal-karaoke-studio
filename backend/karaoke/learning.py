"""Learning stats, derived each time from the songs, the practice log and the line ratings (nothing stored here).

- Vocabulary: a word's form is its letters (Hebrew: no points or punctuation, so "שָׁלוֹם" and "שלום," match;
  Spanish: lower case, accents kept, so "Está" and "está," match but "esta" doesn't).
  Prefixes are not split off: ובלבב and לבב count as different forms. "New to you" = forms not found in any
  song you have studied (practised or rated), other than this one.
- Difficulty 1-5: the share of new forms and how fast the words are sung.
- Mastery: the line ratings (know it = 1, shaky = 0.5, don't know / unrated = 0).
- Review date: the last day you studied the song plus an interval that grows with mastery.
Only counts and ids leave this module (rule 5).
"""
from datetime import date, timedelta

from .text import letters

KNOW, SHAKY, DONT_KNOW = 2, 1, 0
RATINGS = (DONT_KNOW, SHAKY, KNOW)
# (mastery below, review again after N days): weak songs come back tomorrow, solid ones in three weeks.
INTERVALS = ((0.4, 1), (0.7, 3), (0.9, 7), (1.01, 21))
SLOW_WPM, FAST_WPM = 60, 160  # words per sung minute mapped to 0..1 for difficulty
NEW_WEIGHT, SPEED_WEIGHT = 0.6, 0.4


def forms(song: dict) -> dict[str, str]:
    """word id -> form, for words with letters of the song's language."""
    out = {}
    language = song.get("song", {}).get("language", "he")
    for line in song["lines"]:
        for w in line["words"]:
            if f := letters(w["plain"], language):
                out[w["id"]] = f
    return out


def words_per_minute(song: dict) -> float:
    """Words per minute of singing (each line from its first word to its last, so instrumental breaks don't count)."""
    sung_ms = sum(max(0, line["words"][-1]["endMs"] - line["words"][0]["startMs"]) for line in song["lines"] if line["words"])
    count = sum(len(line["words"]) for line in song["lines"])
    return round(count * 60000 / sung_ms, 1) if sung_ms else 0.0


def mastery(ratings: dict[str, int], line_count: int) -> float:
    if not line_count:
        return 0.0
    return round(sum(1.0 if r == KNOW else 0.5 if r == SHAKY else 0.0 for r in ratings.values()) / line_count, 3)


def due_day(studied_on: str | None, mastery_: float) -> str | None:
    """When to review next: None until the song has been studied."""
    if not studied_on:
        return None
    days = next(d for limit, d in INTERVALS if mastery_ < limit)
    return (date.fromisoformat(studied_on) + timedelta(days=days)).isoformat()


def difficulty(new_share: float, wpm: float) -> int:
    speed = min(1.0, max(0.0, (wpm - SLOW_WPM) / (FAST_WPM - SLOW_WPM)))
    return 1 + round(4 * (NEW_WEIGHT * new_share + SPEED_WEIGHT * speed))


def library_stats(songs: dict[str, dict], studied: set[str], ratings: dict[str, dict[str, int]],
                  last_studied: dict[str, str | None]) -> dict[str, dict]:
    """Per song: vocabulary counts, speed, difficulty, mastery and review date; plus the ids of its new words."""
    song_forms = {sid: forms(s) for sid, s in songs.items()}
    form_sets = {sid: set(f.values()) for sid, f in song_forms.items()}
    out = {}
    for sid, song in songs.items():
        mine = form_sets[sid]
        known = set().union(*(form_sets[o] for o in studied if o != sid and o in form_sets))
        elsewhere = set().union(*(fs for o, fs in form_sets.items() if o != sid))
        new = mine - known
        wpm = words_per_minute(song)
        r = ratings.get(sid, {})
        m = mastery(r, len(song["lines"]))
        out[sid] = {
            "forms": len(mine), "newToYou": len(new), "inOtherSongs": len(mine & elsewhere), "wpm": wpm,
            "difficulty": difficulty(len(new) / len(mine) if mine else 0.0, wpm),
            "mastery": m, "rated": len(r), "lines": len(song["lines"]),
            "know": sum(1 for v in r.values() if v == KNOW), "shaky": sum(1 for v in r.values() if v == SHAKY),
            "dontKnow": sum(1 for v in r.values() if v == DONT_KNOW),
            "lastStudied": last_studied.get(sid), "dueDay": due_day(last_studied.get(sid), m),
            "newWordIds": [wid for wid, f in song_forms[sid].items() if f in new],
        }
    return out
