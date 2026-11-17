"""Excerpt guard: warns before exporting too much of a song whose permission is not Granted.

Rules (thresholds in data/guard.json):
- any single continuous stretch of song audio longer than maxContinuousSeconds;
- the parts of the song used (each moment counted once, however often it repeats) over maxShareOfSong of its length;
- lesson videos only: song audio playing for over maxShareOfVideo of the runtime.
All three tracks (original, vocals, instrumental) count as the song's audio. Overlays and subtitles carry no
audio themselves, but their range is the stretch of song they are made to sit on, so it is checked the same way.
"""
import json

from . import paths

DEFAULTS = {"maxContinuousSeconds": 30, "maxShareOfSong": 0.25, "maxShareOfVideo": 0.5}


def load_rules() -> dict:
    path = paths.DATA / "guard.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    return {k: float(data.get(k, v)) for k, v in DEFAULTS.items()}


def covered_ms(ranges: list[tuple[int, int]]) -> int:
    """Length of the union of song ranges (a moment heard twice counts once)."""
    total, end = 0, -1
    for a, b in sorted(ranges):
        if b > end:
            total += b - max(a, end)
            end = b
    return total


def check(plays: list[tuple[int, int, int]], song_ms: int, video_ms: int | None, rules: dict | None = None) -> list[str]:
    """plays: (fromMs, toMs, playedMs) for every time song audio is heard; playedMs differs at slowed speeds.
    video_ms: the lesson's runtime, or None for overlays/subtitles. Returns human-readable warnings."""
    r = rules or load_rules()
    warnings = []
    longest = max((b - a for a, b, _ in plays), default=0)
    if longest > r["maxContinuousSeconds"] * 1000:
        warnings.append(f"continuous song audio of {longest / 1000:.1f} s (limit {r['maxContinuousSeconds']:g} s)")
    share = covered_ms([(a, b) for a, b, _ in plays]) / song_ms if song_ms else 0
    if share > r["maxShareOfSong"]:
        warnings.append(f"uses {share:.0%} of the song (limit {r['maxShareOfSong']:.0%})")
    if video_ms:
        played = sum(p for _, _, p in plays) / video_ms
        if played > r["maxShareOfVideo"]:
            warnings.append(f"song audio is {played:.0%} of the video (limit {r['maxShareOfVideo']:.0%})")
    return warnings
