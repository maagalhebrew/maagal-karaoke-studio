"""Learning stats: vocabulary forms, speed, difficulty, mastery, review dates (pure functions, no files)."""
from karaoke import learning


def song(lines):
    """lines: list of (plain words, start ms, end ms); words spread evenly over the line."""
    out = []
    for i, (words, a, b) in enumerate(lines, 1):
        step = (b - a) // len(words)
        out.append({"id": f"L{i}", "english": "", "words": [
            {"id": f"L{i}W{k}", "plain": w, "startMs": a + (k - 1) * step, "endMs": a + k * step}
            for k, w in enumerate(words, 1)]})
    return {"lines": out, "sections": [], "drills": []}


def test_forms_ignore_points_and_punctuation_but_not_prefixes():
    s = song([(["שָׁלוֹם,", "שלום", "ושלום", "!"], 0, 4000)])
    assert learning.forms(s) == {"L1W1": "שלום", "L1W2": "שלום", "L1W3": "ושלום"}  # "!" has no letters


def test_speed_counts_only_sung_time():
    s = song([(["א"] * 10, 0, 6000), (["ב"] * 10, 60000, 66000)])  # 20 words in 12 s of singing, a minute apart
    assert learning.words_per_minute(s) == 100.0


def test_mastery_and_review_interval_grow_together():
    assert learning.mastery({"L1": 2, "L2": 1}, 4) == 0.375  # (1 + 0.5) / 4; unrated lines count as 0
    assert learning.due_day(None, 1.0) is None  # not studied yet
    assert learning.due_day("2026-11-01", 0.2) == "2026-11-02"
    assert learning.due_day("2026-11-01", 0.5) == "2026-11-04"
    assert learning.due_day("2026-11-01", 0.8) == "2026-11-08"
    assert learning.due_day("2026-11-01", 1.0) == "2026-11-22"


def test_difficulty_and_new_words_follow_what_you_studied():
    a = song([(["שלום", "עולם"], 0, 2000)])
    b = song([(["שלום", "ילד", "עולם"], 0, 3000)])
    stats = learning.library_stats({"a": a, "b": b}, studied=set(), ratings={}, last_studied={})
    assert stats["b"]["newToYou"] == 3 and stats["b"]["inOtherSongs"] == 2  # nothing studied: all new to you
    stats = learning.library_stats({"a": a, "b": b}, studied={"a"}, ratings={"a": {"L1": 2}}, last_studied={"a": "2026-11-01"})
    assert stats["b"]["newToYou"] == 1 and stats["b"]["newWordIds"] == ["L1W2"]  # only ילד is new
    assert stats["a"]["mastery"] == 1.0 and stats["a"]["dueDay"] == "2026-11-22" and stats["b"]["dueDay"] is None
    assert learning.difficulty(0.0, 50) == 1 and learning.difficulty(1.0, 200) == 5
    assert stats["b"]["difficulty"] < learning.difficulty(1.0, stats["b"]["wpm"])  # knowing words makes it easier
