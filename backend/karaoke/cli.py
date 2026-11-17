"""`karaoke` command line. Output is counts, ids and stage status only — never lyric text."""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from .paths import SONGS


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "song-" + datetime.now().strftime("%Y%m%d-%H%M%S")


def cmd_add(args) -> int:
    from .stages import STAGES, Song, StageError, run

    summary = {"ok": False, "song": None, "folder": None, "stages": [], "error": None}

    def emit_error(stage: str, message: str) -> int:
        summary["error"] = {"stage": stage, "message": message}
        if args.json:
            print(json.dumps(summary, ensure_ascii=False))
        else:
            print(f"FAILED at stage {STAGES.index(stage) + 1 if stage in STAGES else '?'} ({stage}): {message}")
        return 1

    audio, lyrics = Path(args.audio).resolve(), Path(args.lyrics).resolve()
    for label, p in (("audio", audio), ("lyrics", lyrics)):
        if not p.is_file():
            return emit_error("ingest", f"{label} file not found: {p.name}")

    slug = slugify(args.slug or audio.stem)
    folder = SONGS / slug
    summary.update(song=slug, folder=str(folder))
    if (folder / "song.json").exists() and not args.force:
        return emit_error("ingest", f"song '{slug}' already exists; use --force to rebuild it (song.json is backed up)")

    song = Song(slug=slug, folder=folder, audio_src=audio, lyrics_src=lyrics, title=audio.stem, language=args.language,
                english_lines={"auto": None, "yes": True, "no": False}[args.english_lines])

    def on_stage(i, name, ok, secs, info):
        summary["stages"].append({"stage": name, "ok": ok, "seconds": secs,
                                  **({"details": info} if ok else {"error": info})})
        if not args.json and ok:
            counts = ", ".join(f"{k}={v}" for k, v in info.items())
            print(f"[ok] {i}/{len(STAGES)} {name:<13} {secs:>6.1f}s  {counts}", flush=True)

    try:
        run(song, on_stage)
    except StageError as e:
        return emit_error(e.stage, str(e))

    summary["ok"] = True
    if args.json:
        print(json.dumps(summary, ensure_ascii=False))
    else:
        print(f"Done: {folder / 'song.json'}")
    return 0


def cmd_retime(args) -> int:
    from .stages import retime

    folder = SONGS / args.song
    if not (folder / "song.json").is_file():
        print(f"song '{args.song}' not found")
        return 1
    result = retime(folder)
    print(json.dumps(result) if args.json else
          f"{args.song}: {result['wordsMoved']} word(s) moved out of instrumental gaps, {result['linesChanged']} line(s) changed"
          + (" (previous song.json kept in backups)" if result["wordsMoved"] else ""))
    return 0


def cmd_translate(args) -> int:
    from .stages import translate_song

    folder = SONGS / args.song
    if not (folder / "song.json").is_file():
        print(f"song '{args.song}' not found")
        return 1
    d = translate_song(folder, args.model, redo=args.all)
    print(json.dumps(d) if args.json else f"{args.song}: English added to {d.get('translated', 0)} line(s)"
          + (f"; {d['skipped']}" if d.get("skipped") else ""))
    return 0


def cmd_migrate(args) -> int:
    """Upgrade every song.json to the current schema (counts only; old files kept in each song's backups)."""
    from .songfile import migrate_folder

    results, failed = {}, 0
    for folder in sorted(SONGS.iterdir()) if SONGS.is_dir() else []:
        if not (folder / "song.json").is_file():
            continue
        try:
            results[folder.name] = migrate_folder(folder)
        except (ValueError, KeyError) as e:
            failed += 1
            results[folder.name] = {"error": str(e)[:200]}
    if args.json:
        print(json.dumps(results))
    else:
        for name, r in results.items():
            print(f"{name}: " + ("already current" if r is None else f"FAILED ({r['error']})" if "error" in r else
                                 f"schema {r['from']} -> {r['to']}, {r['words']} words, {r['flagsRemoved']} old flags removed, "
                                 f"{r['drillStepsUpdated']} drill steps updated"))
        upgraded = sum(1 for r in results.values() if r and "error" not in r)
        print(f"{upgraded} upgraded, {sum(r is None for r in results.values())} already current, {failed} failed")
    return 1 if failed else 0


def cmd_serve(args) -> int:
    import uvicorn

    from .paths import FRONTEND_DIST
    if not FRONTEND_DIST.is_dir():
        print("note: frontend/dist not built yet (run `npm run build` in frontend); serving the API only")
    print(f"Editor: http://127.0.0.1:{args.port}/", flush=True)
    print_due()
    uvicorn.run("karaoke.api:app", host="127.0.0.1", port=args.port, log_level="warning")
    return 0


def print_due() -> None:
    """Launch reminder: permission requests whose follow-up date has come."""
    from . import permissions

    due = permissions.due()
    if due:
        print(f"Follow-up due on {len(due)} permission request(s):")
        for r in due:
            print(f"  {r['song_id']}: asked {r['asked_on']}, follow up {r['follow_up_on']} ({r['artist'] or 'no artist'})")
    sys.stdout.flush()  # the server runs right after; don't leave the reminder in the buffer


def cmd_permissions(args) -> int:
    from . import permissions

    if args.action == "set":
        if not (SONGS / args.song / "song.json").is_file():
            print(f"song '{args.song}' not found")
            return 1
        changes = {f: getattr(args, f) for f in permissions.FIELDS if getattr(args, f) is not None}
        try:
            rec = permissions.save(args.song, changes)
        except permissions.RecordError as e:
            print(e)
            return 1
        print(json.dumps(rec, ensure_ascii=False) if args.json else f"{args.song}: {rec['status']}"
              + (f", asked {rec['asked_on']}, follow up {rec['follow_up_on']}" if rec["asked_on"] else ""))
    elif args.action == "log":
        rows = permissions.export_log(args.song)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False))
        for r in [] if args.json else rows:
            print(f"#{r['id']} {r['at']} {r['song_id']} {r['kind']} [{r['permission_status']}] "
                  f"{len(r['ranges'])} range(s)" + (f" OVERRIDE: {r['override_reason']}" if r["override_reason"] else ""))
    else:
        permissions.due()  # refresh 'Follow-up due' before listing
        records = permissions.all_records()
        rows = [records.get(f.name) or permissions.get(f.name) for f in sorted(SONGS.iterdir()) if (f / "song.json").is_file()] \
            if SONGS.is_dir() else []
        if args.json:
            print(json.dumps(rows, ensure_ascii=False))
        for r in [] if args.json else rows:
            print(f"{r['song_id']:<28} {r['status']:<14} follow up {r['follow_up_on'] or '-':<10}  {r['artist']}")
    return 0


def cmd_export(args) -> int:
    from .export import TIERS, ExportError, GuardError, export_lesson, export_overlay, export_subs

    try:
        if args.kind == "lesson":
            result = export_lesson(args.song, args.drill, args.preset, args.background, args.override)
        elif args.kind == "overlay":
            tiers = tuple(t for t in args.tiers.split(",") if t)
            if not tiers or any(t not in TIERS for t in tiers):
                raise ExportError(f"--tiers must be a comma list of {', '.join(TIERS)}")
            result = export_overlay(args.song, args.from_s, args.to_s, args.preset, tiers, args.override)
        else:
            result = export_subs(args.song, args.from_s, args.to_s, args.preset, args.override)
    except GuardError as e:
        print(json.dumps({"ok": False, "error": str(e), "guard": {"permission": e.status, "warnings": e.warnings}})
              if args.json else f"Export stopped by the {e}")
        return 3
    except ExportError as e:
        print(json.dumps({"ok": False, "error": str(e)}) if args.json else f"Export failed: {e}")
        return 1
    if args.json:
        print(json.dumps({"ok": True, **result}, ensure_ascii=False))
    else:
        for k, v in result.items():
            print(f"{k}: {v}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="karaoke", description="Hebrew Karaoke Studio")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add", help="process one song: audio + lyrics.txt -> songs/<slug>/song.json")
    add.add_argument("audio", help="MP3, M4A or WAV")
    add.add_argument("lyrics", help="UTF-8 lyrics.txt (one sung line per line, blank line between sections)")
    add.add_argument("--json", action="store_true", help="print one JSON summary instead of progress lines")
    add.add_argument("--slug", help="song folder name (default: from the audio file name)")
    add.add_argument("--force", action="store_true", help="rebuild an existing song (previous song.json is backed up)")
    add.add_argument("--language", choices=["he", "es"], default="he", help="the song's language: he (Hebrew) or es (Spanish)")
    add.add_argument("--english-lines", choices=["auto", "yes", "no"], default="auto",
                     help="is each lyric line followed by its English? auto = detect (Hebrew only)")
    rt = sub.add_parser("retime", help="move lyrics out of instrumental passages, using where Whisper hears singing "
                                       "(keeps other timing edits; previous song.json is backed up)")
    rt.add_argument("song")
    rt.add_argument("--json", action="store_true")
    tr = sub.add_parser("translate", help="fill in missing English with the local model (Ollama); "
                                          "previous song.json is backed up")
    tr.add_argument("song")
    tr.add_argument("--model", help="an Ollama model name (default: data/translate.json)")
    tr.add_argument("--all", action="store_true", help="redo every line, replacing the English already there")
    tr.add_argument("--json", action="store_true")
    mig = sub.add_parser("migrate", help="upgrade every song.json to the current schema (old files kept in backups)")
    mig.add_argument("--json", action="store_true")
    serve = sub.add_parser("serve", help="run the editor on http://127.0.0.1:<port>/ (this machine only)")
    serve.add_argument("--port", type=int, default=8321)

    export = sub.add_parser("export", help="render a lesson video, caption overlay or subtitles into songs/<slug>/exports/")
    kinds = export.add_subparsers(dest="kind", required=True)
    lesson = kinds.add_parser("lesson", help="MP4 (H.264, 1920x1080) of a drill; needs at least one teaching card")
    lesson.add_argument("song")
    lesson.add_argument("--drill", required=True, help="drill id, e.g. D1")
    lesson.add_argument("--background", default="#0b1020", help="#rrggbb, or your own image/video file")
    overlay = kinds.add_parser("overlay", help="transparent ProRes 4444 .mov of the captions, on the song's timeline")
    overlay.add_argument("song")
    overlay.add_argument("--tiers", default="lyrics,en")
    subs = kinds.add_parser("subs", help="SRT per tier + one styled ASS")
    subs.add_argument("song")
    for p in (lesson, overlay, subs):
        p.add_argument("--preset", default="default", help="style preset from data/presets.json")
        p.add_argument("--override", metavar="REASON",
                       help="export even if the excerpt guard warns (song not Granted); the reason is logged")
        p.add_argument("--json", action="store_true")
    for p in (overlay, subs):
        p.add_argument("--from", dest="from_s", type=float, help="start, seconds into the song (default 0)")
        p.add_argument("--to", dest="to_s", type=float, help="end, seconds into the song (default: song end)")

    perms = sub.add_parser("permissions", help="permission tracker and export log (data/karaoke.db)")
    actions = perms.add_subparsers(dest="action")
    actions.add_parser("list", help="every song's permission status (the default)")
    pset = actions.add_parser("set", help="create or update a song's permission record")
    pset.add_argument("song")
    for field in ("artist", "contact_name", "contact_channel", "contact_handle", "asked_on", "follow_up_on", "scope", "reply_path"):
        pset.add_argument(f"--{field.replace('_', '-')}", dest=field)
    pset.add_argument("--status", help="Not asked / Asked / Follow-up due / Granted / Declined / No answer")
    plog = actions.add_parser("log", help="export log, newest first")
    plog.add_argument("song", nargs="?")
    for p in (perms, pset, plog):
        p.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if args.command == "add":
        return cmd_add(args)
    if args.command == "permissions":
        return cmd_permissions(args)
    if args.command == "translate":
        return cmd_translate(args)
    if args.command == "retime":
        return cmd_retime(args)
    if args.command == "migrate":
        return cmd_migrate(args)
    if args.command == "serve":
        return cmd_serve(args)
    if args.command == "export":
        return cmd_export(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
