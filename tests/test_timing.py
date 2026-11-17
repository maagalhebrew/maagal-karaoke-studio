"""Stage 5 timing clean-up: monotonic, every word >= 40 ms, inside the song; transcript correction."""
from karaoke.stages import MIN_WORD_MS, _enforce_timing, correct_from_transcript


def words(*spans):
    return [{"id": f"L1W{i}", "startMs": s, "endMs": e, "flags": []} for i, (s, e) in enumerate(spans, 1)]


def valid(ws, duration):
    prev = 0
    for w in ws:
        assert prev <= w["startMs"] and w["endMs"] - w["startMs"] >= MIN_WORD_MS and w["endMs"] <= duration
        prev = w["endMs"]


def test_good_timing_untouched():
    ws = words((0, 100), (100, 300))
    assert _enforce_timing(ws, 1000) == 0 and not any(w["flags"] for w in ws)


def test_overlap_and_short_words_fixed():
    ws = words((0, 100), (50, 60), (60, 60))
    assert _enforce_timing(ws, 1000) == 2
    valid(ws, 1000)
    assert ws[1]["flags"] == ["timing-adjusted"]


def test_pile_up_at_song_end_pulled_back():
    ws = words((900, 1000), (1000, 1000), (1000, 1000), (1000, 1000))
    _enforce_timing(ws, 1000)
    valid(ws, 1000)


# --- correction from the free transcription (Latin stand-in words; only letters matter) ---------------------
def lyric(spans):
    return [{"id": f"L1W{i}", "plain": p, "startMs": s, "endMs": e, "flags": []} for i, (p, s, e) in enumerate(spans, 1)]


# Whisper hears a, b, then nothing from 1.0 s to 10.0 s (instrumental), then c d e, a misheard word, g.
HEARD = [("a", 0, 500), ("b", 500, 1000), ("c", 10000, 10500), ("d", 10500, 11000), ("e", 11000, 11500),
         ("xx", 11500, 12000), ("g", 12000, 12500)]


def test_lines_pulled_into_an_instrumental_move_to_where_they_are_heard():
    ws = lyric([("a", 0, 500), ("b", 500, 1000), ("c", 3000, 3500), ("d", 3500, 4000), ("e", 4000, 4500),
                ("f", 4500, 6000), ("g", 12000, 12500)])
    assert correct_from_transcript(ws, HEARD) == 4
    assert [(w["startMs"], w["endMs"]) for w in ws[2:5]] == [(10000, 10500), (10500, 11000), (11000, 11500)]
    assert (ws[5]["startMs"], ws[5]["endMs"]) == (11500, 12000)  # unmatched word re-spaced after its neighbour
    assert [w["flags"] for w in ws] == [[], [], ["timing-adjusted"], ["timing-adjusted"], ["timing-adjusted"],
                                        ["timing-adjusted"], []]
    valid(ws, 13000)


def test_words_already_where_they_are_heard_are_untouched():
    ws = lyric([(k, s, e) for k, s, e in HEARD if k != "xx"])
    assert correct_from_transcript(ws, HEARD) == 0 and not any(w["flags"] for w in ws)


def test_fewer_than_three_matching_words_are_not_trusted():
    heard = [("a", 0, 500), ("q", 500, 1000), ("c", 10000, 10500), ("d", 10500, 11000), ("z", 11000, 11500)]
    ws = lyric([("a", 0, 500), ("b", 500, 1000), ("c", 3000, 3500), ("d", 3500, 4000), ("e", 4000, 4500)])
    assert correct_from_transcript(ws, heard) == 0


def test_singing_before_the_first_heard_word_is_not_a_gap():
    # Whisper often misses a quiet first or last line: that stretch must not count as instrumental
    ws = lyric([("c", 2000, 2500), ("d", 2500, 3000), ("e", 3000, 3500)])
    assert correct_from_transcript(ws, HEARD[2:]) == 0
