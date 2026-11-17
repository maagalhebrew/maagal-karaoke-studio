# Hebrew Karaoke Studio — Claude Code Handoff

Target machine: Windows 11 with an NVIDIA GPU (developed on an RTX 3050 laptop GPU, 6 GB VRAM).
Project root: the folder holding this file (`<project>` below). Spec version: 27 Oct 2026.

## What we are building

A local Windows app that turns one Hebrew song into an editable lesson:
two-line lyrics timed word by word to the music, sections and sub-ranges the user can split and loop,
repeat drills, and teaching-format lesson videos for YouTube.

Caption tiers, top to bottom:
1. The lyrics as written (vowel points, if the pasted lyrics have them, can be hidden)
2. English (from the local translation model, editable)

User decision 17 Nov 2026: the niqqud model and the transliteration tier are dropped; the music carries the
pronunciation. Spanish songs come next (see `docs\build-plan.md`, milestones M7 to M13).

Out of scope for v1: pitch scoring, mobile, cloud hosting, multi-user, vertical (1080x1920) export.

## Working rules (read before every session)

1. Build milestone by milestone (M0 to M6 below). After each milestone, run its acceptance tests for real,
   show the output, and STOP for the user's go-ahead. Never mark a milestone done on a claim; done = tests ran and passed.
2. Explain each step in plain English before running it. The user is learning; spell out acronyms on first use.
3. Windows + PowerShell. Use `py -3.11` / a venv at `<project>\.venv`. Paths with backslashes in docs, `pathlib` in code.
4. GPU memory rule: load one model at a time and free it (`del model; torch.cuda.empty_cache()`) before the next.
   Demucs, Whisper and the local English model never sit in VRAM together. Fallback: smaller model or CPU for that stage.
5. Lyrics privacy: song lyrics stay on this machine. Never print a user song's lyric text in chat, logs or
   CLI output — report counts, ids and stage status instead. The only lyrics you may display are the public-domain
   test fixture (Hatikvah, below).
6. Check current install commands (PyTorch CUDA wheel, model ids) against official pages before using them;
   versions move.
7. Commit to Git at the end of every milestone with a message naming it.

## Tech stack

| Layer | Choice |
| --- | --- |
| App shell | FastAPI (Python) on localhost + React/TypeScript front end built with Vite, used in Chrome |
| Vocal separation | Demucs v4, `htdemucs`, `--two-stems vocals`, `--shifts 0` (deterministic: the default random shift made alignment quality vary run to run, once failing completely) |
| PyTorch | 2.14.1 **CUDA 12.6 build** (`/whl/cu126`). Not cu130: CTranslate2 (faster-whisper) needs CUDA 12 DLLs and reuses torch's — import torch before faster_whisper |
| English | Local model via Ollama (optional: the song completes without it) |
| Timing | `stable-ts` `align()` via faster-whisper, model by the song's language (`backend/karaoke/models.py`): Hebrew `ivrit-ai/whisper-large-v3-turbo-ct2`; Spanish (M8) `mobiuslabsgmbh/faster-whisper-large-v3-turbo` (the multilingual turbo model, MIT) |
| Waveform editing | wavesurfer.js + Regions plugin |
| Playback | Web Audio / HTMLMediaElement, `playbackRate` with `preservesPitch = true` |
| Video rendering | Remotion 4 (free license: individual / company of up to 3 people). Audio: `<Audio>` from `@remotion/media` with `preservePitch` set EXPLICITLY (left to its default, 75% renders came out 25% lower in pitch) |
| Resolve handoff | ProRes 4444 .mov with alpha + SRT files |
| Storage | One folder per song (audio + `song.json`); SQLite for library + permissions |
| Font | Heebo (Hebrew + Latin, Open Font License), bundled locally |

## Repository layout (target)

```
<project>
  CLAUDE.md
  inbox\                 # user drops audio + lyrics.txt here
  songs\<slug>\          # audio\original.wav, vocals.wav, instrumental.wav, song.json, report.json, backups\
  data\karaoke.db        # SQLite: library, permissions, export log
  backend\               # FastAPI app + pipeline package + CLI (`karaoke`)
  frontend\              # React + Vite editor
  render\                # Remotion project (imports caption components from frontend\src\captions)
  skills\karaoke-add-song\SKILL.md
  tests\fixtures\hatikvah\lyrics.txt
```

## Processing pipeline — `karaoke add <audio> <lyrics.txt> [--json]` (five stages since M7)

Each stage writes to the song folder and must pass its checkpoint; a failed checkpoint stops the run and names the stage.

1. **Ingest.** Audio (MP3/M4A/WAV/WebM/Opus/OGG) -> 44.1 kHz stereo WAV, brought to about -14 LUFS with one fixed gain (never single-pass loudnorm: it rides the volume and flattens the song).
   Lyrics: UTF-8, one sung line per line, blank line between sections, optional labels like `[chorus]`.
   Checkpoint: audio decodes with a duration; at least one Hebrew line.
2. **Separate.** Demucs -> `vocals.wav`, `instrumental.wav`. Checkpoint: both exist, length within 0.1 s of original.
3. **Translate.** English for lines that have none, from the local model. Never fails the song: skipped if the
   model is off.
4. **Align.** stable-ts forced alignment of the PLAIN lyrics against `vocals.wav`, then `refine()`.
   Output start/end ms + confidence per word. Checkpoint: times monotonic, no word under 40 ms,
   words under 0.5 confidence flagged.
5. **Assemble.** Write `song.json` (schema below) and `report.json` (all flags, counts by type).
   Sections from blank lines/labels.

## Data model (`song.json`)

Words are the atoms; lines, sections, clips and drills point at word ranges. Times are integer milliseconds.
`plain` is the word as written. A word's spelling marks (vowel points, punctuation, case) may be edited, never its
letters. Every save keeps the previous file in `backups\` with a number. Schema 1 songs (with `pointed` and
`syllables`) are upgraded to schema 2 when read (`songfile.migrate`).

```json
{
  "schema": 2,
  "song": {"id": "song-slug", "title": "", "artist": "", "language": "he", "permissionId": null,
           "audio": {"original": "audio/original.wav", "vocals": "audio/vocals.wav", "instrumental": "audio/instrumental.wav"},
           "durationMs": 0},
  "lines": [{"id": "L1", "english": "", "words": [
    {"id": "L1W1", "plain": "שלום", "startMs": 0, "endMs": 0, "confidence": 0.0, "flags": []}]}],
  "sections": [{"id": "S1", "kind": "verse", "label": "Verse 1", "fromLine": "L1", "toLine": "L4"}],
  "clips": [{"id": "C1", "name": "", "fromWord": "L1W1", "toWord": "L1W3", "padBeforeMs": 300, "padAfterMs": 300}],
  "drills": [{"id": "D1", "name": "", "steps": [
    {"type": "clip", "clip": "C1", "repeats": 3, "speed": 0.75, "track": "original", "yourTurn": true, "tiers": ["lyrics", "en"]},
    {"type": "card", "text": "Shalom means hello", "durationMs": 4000}]}]
}
```

Section kinds: verse, chorus, bridge, intro, outro, transition, custom. A chorus heard three times = three sections.

## Editor UI

One screen, three stacked bands:
- **Preview:** captions exactly as rendered; active word highlighted with a wipe. Hebrew lyrics `dir="rtl"`; time axis left-to-right.
- **Timeline:** vocals waveform, section bands colored by kind, ticks at word boundaries, zoom from whole song to 2 s.
- **Lanes:** the lyric words and one English field per line.
- **Flags panel:** every flagged word; click jumps to it. Zero flags = song done.

Interactions:
- Drag word edges; arrow keys nudge 10 ms (Shift 50 ms). Tap-to-time: play a line, Space at each word start.
- Double-click a word to fix its timing or spelling (same letters), add or delete a word, or change where lines break.
- Select any range (drag on waveform or Shift-click two words) -> make a section (pick kind) or a clip (down to one word).
- Drill builder: steps = clip or teaching card; per clip step: repeats 1-10, speed 50-100%, track
  (original / instrumental / vocals), tiers shown (lyrics, English), "your turn" gap (silence equal to clip length, captions held).
- Practice mode: full-screen captions. Keys: L loop line, [ ] speed, V toggle original/instrumental, Space play/pause.
- Autosave every edit.

## Video export (Remotion, same caption components as the editor)

| Export | Format |
| --- | --- |
| Lesson video | MP4, H.264, 1920x1080 |
| Caption overlay | ProRes 4444 .mov, transparent background |
| Subtitles | SRT per tier + one styled ASS with both tiers, the lyrics filling word by word |

- Lesson video requires at least one teaching card.
- Style presets: per-tier size (lyrics 100%, English ~60%), colors, highlight color,
  box opacity, vertical position; text inside the 90% title-safe area.
- Backgrounds: solid color, still image, or a user-supplied video. Never artwork or footage from the original song.

## Permissions tracker and excerpt guard

Publishing strategy: teaching-format excerpts (fair use, Israeli Copyright Act section 19) + written artist permission.

Tracker (SQLite, one record per song): song, artist, contact (name, channel, handle), date asked,
follow-up date (default ask + 10 days), status (Not asked / Asked / Follow-up due / Granted / Declined / No answer),
scope granted, saved reply path.
- "Draft" button fills this Hebrew template with song + artist and copies it:
  `שלום [שם], קוראים לי [השם שלך]. אני לומד עברית דרך שירים, והשיר [שם השיר] הוא אחד האהובים עליי. אני בונה ערוץ יוטיוב ללימוד עברית בשם מעגל, ואשמח לבקש אישור להשתמש בקטעים קצרים מהשיר בסרטון שמלמד את המילים וההגייה, עם קרדיט מלא וקישור לשיר המקורי. תודה רבה! [השם שלך], [טלפון]`
- On launch, list every request past its follow-up date.

Excerpt guard (status not Granted), checked at export:
- Warn: any continuous song audio > 30 s; total song audio > 25% of song length; song audio > 50% of video runtime.
- Block: lesson video with no teaching card.
- Overrides need explicit confirmation and are logged.
- Export log: every export records song ranges used, permission status at that moment, overrides.
Thresholds are configurable working rules, not legal advice.

## The `karaoke-add-song` skill (M6)

Write `skills\karaoke-add-song\SKILL.md` and install it into Claude Code's user skills folder.
Trigger: "add [song] to karaoke" with files in `<project>\inbox`. Steps:
1. Confirm both files exist; lyrics file is UTF-8.
2. Run `karaoke add <audio> <lyrics> --json`.
3. Read stage results + `report.json` COUNTS only. Never read, print, transliterate or translate lyric text.
4. Verify independently: expected files exist, song is in the library, editor URL responds.
5. Create the permission record (status Not asked).
6. Report in three lines: stages passed, words to review (timing), editor link. On failure: stage, error, likely fix.

## Milestones and acceptance tests

Test song for M1-M5: Hatikvah (lyrics by Naftali Herz Imber, published 1886 — public domain).
The user supplies a recording at `<project>\inbox\hatikvah.*` for private local testing.

**M0 — Environment**
- [ ] Python 3.11, Node.js 24 LTS (20 is end-of-life as of Apr 2026), ffmpeg, Git installed (winget where possible)
- [ ] PyTorch with CUDA: `torch.cuda.is_available()` is True and reports the RTX 3050
- [ ] Demucs, menaked (retired in M7) and ivrit.ai Whisper models downloaded and cached
- [ ] Git repo initialized at `<project>`; `.gitignore` excludes `.venv`, `songs\`, `inbox\`, model caches, `data\karaoke.db`

**M1 — Pipeline command**
- [ ] `karaoke add` completes all six stages on the test song
- [ ] `song.json` validates against a JSON Schema; every word has times (stress and transliteration checks retired in M7)
- [ ] Empty lyrics file stops at stage 1 with a clear message

**M2 — Editor**
- [ ] Test song opens; preview, waveform and lanes stay in sync during playback
- [ ] A word-edge drag survives a page reload (the stress checks were retired in M7)

**M3 — Sections, clips, drills**
- [ ] Create a chorus section, a two-word clip and a three-step drill
- [ ] Drill plays repeats, runs at 75% speed with no pitch drop, holds the "your turn" gap

**M4 — Export**
- [ ] A 60-second lesson video with two teaching cards renders at 1920x1080
- [ ] ProRes overlay shows a transparent background on a DaVinci Resolve timeline (user confirms)
- [ ] SRT files import into Resolve as subtitle tracks (user confirms)

**M5 — Permissions and guard**
- [ ] A 45-second continuous excerpt from an ungranted song triggers the guard
- [ ] The override is written to the export log
- [ ] A request past its follow-up date shows on launch

**M6 — Skill**
- [ ] Claude runs `karaoke-add-song` on a second song end to end
- [ ] The report matches `report.json` and contains no lyric text

**M7 onwards** (two lines, Spanish, raw-lyrics cleaning, public build, desktop app, release): see `docs\build-plan.md`.

**Done:** a favorite song goes from inbox to a working drill in under 30 minutes of hands-on time (target).

## Test fixture — Hatikvah lyrics (public domain)

Saved unpointed to `tests\fixtures\hatikvah\lyrics.txt`:

```
כל עוד בלבב פנימה
נפש יהודי הומיה
ולפאתי מזרח קדימה
עין לציון צופיה

עוד לא אבדה תקוותנו
התקווה בת שנות אלפיים
להיות עם חופשי בארצנו
ארץ ציון וירושלים

להיות עם חופשי בארצנו
ארץ ציון וירושלים
```

The last section is the sung repeat of the final two lines (lyrics files list what is SUNG, one sung line per line;
without it ~8 s of singing gets no words). 35 words.

## Known risks

- Whisper models are trained on speech, not singing; held notes and fast runs drift -> flags + tap-to-time.
- Backing vocals leak into `vocals.wav` -> flags cluster there; manual drags.
- 6 GB VRAM -> sequential loading; fallback to smaller model or CPU.
- Remotion license terms (v5.0 change announced) -> recheck before Maagal grows past 3 people.
