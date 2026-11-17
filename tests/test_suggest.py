"""Missing / extra word suggestions (Latin stand-in words: only the letters matter)."""
from karaoke import suggest


def song(*lines):
    """lines of (word, startMs, endMs)."""
    return {"song": {"durationMs": 20000}, "lines": [
        {"id": f"L{n}", "words": [{"id": f"L{n}W{k}", "plain": p, "startMs": s, "endMs": e}
                                  for k, (p, s, e) in enumerate(words, 1)]} for n, words in enumerate(lines, 1)]}


def heard(*words):
    return [[p, s, e, p.upper()] for p, s, e in words]


# lyrics: "one two four" / "five six"; sung: "one two three four" / "five six"
SONG = song([("one", 1000, 1400), ("two", 1500, 2400), ("four", 2600, 3000)], [("five", 4000, 4400), ("six", 4500, 5000)])


def test_word_heard_between_two_lyric_words_is_missing():
    h = heard(("one", 1000, 1400), ("two", 1500, 1900), ("three", 2000, 2400), ("four", 2600, 3000),
              ("five", 4000, 4400), ("six", 4500, 5000))
    [s] = suggest.suggestions(SONG, h)
    assert (s["type"], s["text"], s["wordId"], s["side"], s["startMs"], s["endMs"]) == ("missing", "THREE", "L1W2", "after", 2000, 2400)


def test_word_heard_far_from_the_gap_is_not_suggested():
    h = heard(("one", 1000, 1400), ("two", 1500, 1900), ("three", 9000, 9400), ("four", 2600, 3000),
              ("five", 4000, 4400), ("six", 4500, 5000))
    assert suggest.suggestions(SONG, h) == []


def test_missing_word_near_the_next_line_joins_that_line():
    h = heard(("one", 1000, 1400), ("two", 1500, 2400), ("four", 2600, 3000), ("hey", 3800, 3950),
              ("five", 4000, 4400), ("six", 4500, 5000))
    [s] = suggest.suggestions(SONG, h)
    assert (s["lineId"], s["wordId"], s["side"]) == ("L2", "L2W1", "before")


def test_lyric_word_over_silence_is_unheard_but_not_at_the_edges():
    h = heard(("one", 1000, 1400), ("two", 1500, 2400), ("five", 4000, 4400), ("six", 4500, 5000))
    [s] = suggest.suggestions(SONG, h)
    assert (s["type"], s["wordId"]) == ("unheard", "L1W3")
    # the last line not heard at all: Whisper often misses quiet singing at the end, so no suggestion
    assert suggest.suggestions(SONG, heard(("one", 1000, 1400), ("two", 1500, 2400), ("four", 2600, 3000))) == []


def test_misheard_word_is_not_called_unheard():
    h = heard(("one", 1000, 1400), ("two", 1500, 2400), ("fur", 2600, 3000), ("five", 4000, 4400), ("six", 4500, 5000))
    assert suggest.suggestions(SONG, h) == []


def test_dismissed_suggestions_stay_hidden(tmp_path):
    h = heard(("one", 1000, 1400), ("two", 1500, 1900), ("three", 2000, 2400), ("four", 2600, 3000),
              ("five", 4000, 4400), ("six", 4500, 5000))
    [s] = suggest.suggestions(SONG, h)
    suggest.dismiss(tmp_path, s["key"])
    assert suggest.suggestions(SONG, h, suggest.load_dismissed(tmp_path)) == []
