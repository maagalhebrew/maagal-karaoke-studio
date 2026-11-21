"""`karaoke export`: lesson video (H.264), caption overlay (ProRes 4444 with alpha) and subtitles.

Videos are rendered by the Remotion project in render/ (same caption components as the editor).
Outputs go to songs/<slug>/exports/. Nothing here prints lyric text.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

from . import guard, paths, permissions, subtitles
from .songfile import load

FPS = 30
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_TYPES = {".mp4", ".mov", ".webm"}
TIERS = ("lyrics", "en")


class ExportError(Exception):
    pass


class GuardError(ExportError):
    """The excerpt guard stopped an export of an ungranted song; re-run with an override reason to go ahead."""

    def __init__(self, status: str, warnings: list[str]):
        super().__init__(f"excerpt guard (permission: {status}): " + "; ".join(warnings)
                         + ". To export anyway, give a reason with --override \"...\" (it is logged).")
        self.status, self.warnings = status, warnings


def _check_guard(slug: str, song: dict, plays: list[tuple[int, int, int]], video_ms: int | None,
                 override: str | None) -> dict:
    """Runs before rendering. Returns what the export log needs; raises GuardError if not allowed."""
    status = permissions.get(slug)["status"]
    warnings = guard.check(plays, song["song"]["durationMs"], video_ms)
    override = (override or "").strip() or None
    if status != "Granted" and warnings and not override:
        raise GuardError(status, warnings)
    return {"status": status, "warnings": warnings, "override": override if status != "Granted" and warnings else None,
            "ranges": [(a, b) for a, b, _ in plays]}


def _log(slug: str, kind: str, output: Path, g: dict) -> dict:
    log_id = permissions.log_export(slug, kind, str(output), g["ranges"], g["status"], g["warnings"], g["override"])
    return {"guard": {"permission": g["status"], "warnings": g["warnings"], "override": g["override"], "logId": log_id}}


def load_song(slug: str) -> tuple[Path, dict]:
    folder = paths.SONGS / slug
    if not (folder / "song.json").is_file():
        raise ExportError(f"song '{slug}' not found")
    return folder, load(folder)


def load_preset(name: str) -> dict:
    path = paths.DATA / "presets.json"
    if not path.is_file():
        path = paths.ROOT / "data" / "presets.json"
    presets = json.loads(path.read_text(encoding="utf-8"))["presets"]
    if name not in presets:
        raise ExportError(f"unknown preset '{name}' (have: {', '.join(presets)})")
    return presets[name]


def _clip_range(song: dict, clip: dict) -> tuple[int, int]:
    words = [w for line in song["lines"] for w in line["words"]]
    a = next(w for w in words if w["id"] == clip["fromWord"])
    b = next(w for w in words if w["id"] == clip["toWord"])
    return max(0, a["startMs"] - clip["padBeforeMs"]), min(song["song"]["durationMs"], b["endMs"] + clip["padAfterMs"])


def lesson_duration_ms(song: dict, drill: dict) -> int:
    """Same layout as frontend/src/captions/lesson.ts: card, then per repeat the clip and (optionally) a gap."""
    total = sum(s["durationMs"] for s in drill["steps"] if s["type"] == "card")
    for (start, end, played), step in zip(lesson_plays(song, drill), _clip_steps(drill)):
        total += played * (2 if step["yourTurn"] else 1)
    return total


def _clip_steps(drill: dict):
    """Each clip step once per repeat, in playing order."""
    for step in drill["steps"]:
        if step["type"] == "clip":
            yield from [step] * step["repeats"]


def lesson_plays(song: dict, drill: dict) -> list[tuple[int, int, int]]:
    """(fromMs, toMs, playedMs) of song audio for every clip repeat in the lesson."""
    plays = []
    for step in _clip_steps(drill):
        start, end = _clip_range(song, next(c for c in song["clips"] if c["id"] == step["clip"]))
        plays.append((start, end, round((end - start) / step["speed"])))
    return plays


def parse_background(spec: str) -> dict:
    """'#rrggbb' or a path to an image or video. Never the song's own footage (spec: no artwork or footage
    from the original song), so files from inbox/ or songs/ are refused."""
    if spec.startswith("#"):
        if len(spec) != 7:
            raise ExportError("background colour must look like #0b1020")
        return {"kind": "color", "color": spec}
    path = Path(spec).resolve()
    if not path.is_file():
        raise ExportError(f"background file not found: {path.name}")
    for forbidden in (paths.INBOX, paths.SONGS):
        if path.is_relative_to(forbidden.resolve()):
            raise ExportError("background must be your own image or video, not a file from inbox/ or songs/ "
                              "(never artwork or footage from the original song)")
    ext = path.suffix.lower()
    if ext not in IMAGE_TYPES | VIDEO_TYPES:
        raise ExportError(f"background must be an image ({', '.join(sorted(IMAGE_TYPES))}) or video ({', '.join(sorted(VIDEO_TYPES))})")
    return {"kind": "image" if ext in IMAGE_TYPES else "video", "path": path, "file": f"background{ext}"}


def _stage(folder: Path, background: dict | None) -> Path:
    """Remotion's public dir for this render: the song's audio (hard links, no copying) and the background."""
    stage = folder / "exports" / ".stage"
    shutil.rmtree(stage, ignore_errors=True)
    (stage / "audio").mkdir(parents=True)
    for wav in (folder / "audio").glob("*.wav"):
        try:
            os.link(wav, stage / "audio" / wav.name)
        except OSError:
            shutil.copy2(wav, stage / "audio" / wav.name)
    if background and "path" in background:
        shutil.copy2(background["path"], stage / background["file"])
    return stage


def _remotion(composition: str, props: dict, out: Path, stage: Path, extra: list[str]) -> None:
    cli = paths.ROOT / "render" / "node_modules" / "@remotion" / "cli" / "remotion-cli.js"
    if not cli.is_file():
        raise ExportError("Remotion is not installed: run `npm install` in render/")
    props_file = stage / "props.json"
    props_file.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["node", str(cli), "render", "src/index.ts", composition, str(out), f"--props={props_file}",
           f"--public-dir={stage}", "--log=warn", *extra]
    p = subprocess.run(cmd, cwd=paths.ROOT / "render", capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        tail = [ln for ln in (p.stderr or p.stdout).splitlines() if ln.strip()][-3:]
        raise ExportError(f"Remotion render failed (exit {p.returncode}): {' | '.join(tail)[:500]}")


def probe(path: Path) -> dict:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration:stream=codec_type,codec_name,profile,width,height,pix_fmt,r_frame_rate",
                        "-of", "json", str(path)], capture_output=True, text=True, check=True)
    info = json.loads(p.stdout)
    video = next((s for s in info["streams"] if s["codec_type"] == "video"), {})
    audio = next((s for s in info["streams"] if s["codec_type"] == "audio"), {})
    return {"file": str(path), "sizeMB": round(path.stat().st_size / 1e6, 1), "durationS": round(float(info["format"]["duration"]), 2),
            "video": f"{video.get('codec_name')} {video.get('profile', '')} {video.get('width')}x{video.get('height')} "
                     f"{video.get('pix_fmt')} {video.get('r_frame_rate')}".replace("  ", " "),
            "audio": audio.get("codec_name")}


# --- the three exports ------------------------------------------------------------
def export_lesson(slug: str, drill_id: str, preset: str = "default", background: str = "#0b1020",
                  override: str | None = None) -> dict:
    folder, song = load_song(slug)
    drill = next((d for d in song["drills"] if d["id"] == drill_id), None)
    if drill is None:
        raise ExportError(f"drill {drill_id} not found in '{slug}'")
    # Always blocked, whatever the permission (and no override): a lesson is teaching, not the song.
    if not any(s["type"] == "card" for s in drill["steps"]):
        raise ExportError("a lesson video needs at least one teaching card (add a card step to the drill)")
    style, bg = load_preset(preset), parse_background(background)
    g = _check_guard(slug, song, lesson_plays(song, drill), lesson_duration_ms(song, drill), override)
    out = folder / "exports" / f"lesson-{drill_id}-{preset}.mp4"
    stage = _stage(folder, bg)
    _remotion("Lesson", {"song": song, "drillId": drill_id, "style": style,
                         "background": {k: v for k, v in bg.items() if k != "path"}},
              out, stage, ["--codec=h264"])
    shutil.rmtree(stage, ignore_errors=True)
    return {**probe(out), "expectedS": round(lesson_duration_ms(song, drill) / 1000, 2),
            "cards": sum(s["type"] == "card" for s in drill["steps"]), **_log(slug, "lesson", out, g)}


def _range(song: dict, from_s: float | None, to_s: float | None) -> tuple[int, int]:
    duration = song["song"]["durationMs"]
    a = 0 if from_s is None else round(from_s * 1000)
    b = duration if to_s is None else round(to_s * 1000)
    if not 0 <= a < b <= duration:
        raise ExportError(f"range must be inside the song (0-{duration / 1000:.1f}s) with --from < --to")
    return a, b


def _suffix(song: dict, a: int, b: int) -> str:
    return "" if (a, b) == (0, song["song"]["durationMs"]) else f"-{a / 1000:g}-{b / 1000:g}s"


def export_overlay(slug: str, from_s: float | None = None, to_s: float | None = None, preset: str = "default",
                   tiers: tuple[str, ...] = TIERS, override: str | None = None) -> dict:
    folder, song = load_song(slug)
    a, b = _range(song, from_s, to_s)
    g = _check_guard(slug, song, [(a, b, b - a)], None, override)
    out = folder / "exports" / f"overlay{_suffix(song, a, b)}-{preset}.mov"
    stage = _stage(folder, None)
    # Transparent ProRes 4444 (Remotion docs): PNG frames, yuva444p10le, prores profile 4444.
    _remotion("Overlay", {"song": song, "fromMs": a, "toMs": b, "style": load_preset(preset), "tiers": list(tiers)},
              out, stage, ["--codec=prores", "--prores-profile=4444", "--image-format=png", "--pixel-format=yuva444p10le"])
    shutil.rmtree(stage, ignore_errors=True)
    return {**probe(out), **_log(slug, "overlay", out, g)}


def export_subs(slug: str, from_s: float | None = None, to_s: float | None = None, preset: str = "default",
                override: str | None = None) -> dict:
    folder, song = load_song(slug)
    a, b = _range(song, from_s, to_s)
    g = _check_guard(slug, song, [(a, b, b - a)], None, override)
    style = load_preset(preset)
    out_dir = folder / "exports" / "subs"
    out_dir.mkdir(parents=True, exist_ok=True)
    base = f"{slug}{_suffix(song, a, b)}"
    files = {}
    for tier in TIERS:
        text = subtitles.srt(song, tier, a, b, style["showNiqqud"])
        if text:
            path = out_dir / f"{base}.{tier}.srt"
            path.write_text(text, encoding="utf-8")
            files[tier] = {"file": str(path), "cues": text.count(" --> ")}
    path = out_dir / f"{base}.ass"
    path.write_text(subtitles.ass(song, style, a, b), encoding="utf-8-sig")
    files["ass"] = {"file": str(path), "events": path.read_text(encoding="utf-8-sig").count("\nDialogue:")}
    return {**files, **_log(slug, "subs", out_dir / base, g)}
