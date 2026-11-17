---
name: karaoke-add-song
description: Add a Hebrew song to the Hebrew Karaoke Studio from the inbox folder (audio + lyrics.txt), run the five-stage pipeline, verify it, create its permission record and report counts only. Use when the user says "add [song] to karaoke" or asks to process a song from <project>\inbox.
---

# Add a song to Hebrew Karaoke Studio

Project root: `<project>` (call it ROOT). Shell: PowerShell.

## Privacy rule (applies to every step)

Song lyrics stay on this machine. NEVER read, print, quote, transliterate or translate lyric text —
not from `lyrics.txt`, `song.json`, the API, or any command output. Do not open those files with Read,
`Get-Content`, `cat` or similar, and never print an API response body that contains words.
Work only with file names, sizes, counts, ids, stage names, status codes and error messages.
If a command would print lyric text, do not run it.

## Steps

### 1. Find the files and check them

- List `ROOT\inbox` (names and sizes only). Pick the audio file (MP3/M4A/WAV/MP4) and the lyrics `.txt`
  that match the song the user named. If the match is not obvious, or a file is missing, ask the user —
  do not guess.
- Check the lyrics file is UTF-8 without printing it:
  ```powershell
  & "ROOT\.venv\Scripts\python.exe" -c "import sys; open(sys.argv[1], encoding='utf-8').read()" "<lyrics path>"
  ```
  No output = OK. A `UnicodeDecodeError` means the file is not UTF-8: tell the user to re-save it as
  UTF-8 (Notepad: File > Save as > Encoding: UTF-8) and stop.
- Choose a short Latin slug for the song folder (e.g. `karvahal`, lower-case, hyphens). If
  `ROOT\songs\<slug>\song.json` already exists, ask the user before adding `--force`: it rebuilds the
  song and replaces their timing edits (the old `song.json` is kept in `backups\`).

### 2. Run the pipeline

Reload PATH first (ffmpeg is found through it), then run from ROOT. It takes a few minutes; use a
10-minute timeout.
```powershell
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
& "ROOT\.venv\Scripts\karaoke.exe" add "<audio path>" "<lyrics path>" --slug <slug> --json
```
The output is one JSON line: `ok`, `song`, `folder`, `stages` (each with `stage`, `ok`, `seconds` and
count `details`) and `error` (`stage`, `message`). Exit code 0 = all five stages passed. The translate stage never fails the song: if its details say
`skipped`, the English was left empty (usually Ollama isn't running) — mention that in the report.

### 3. Read the results — counts only

Read `ROOT\songs\<slug>\report.json` and use only `stages` and `counts`
(`words`, `lines`, `sections`, `flaggedWords`, `flagsByType`, `wordsToReview.timing`).
The `flags` list holds word ids and flag types only; you may count it, nothing more.

### 4. Verify independently (do not trust the pipeline's own summary)

- Files exist: `song.json`, `report.json`, `audio\original.wav`, `audio\vocals.wav`, `audio\instrumental.wav`.
- The editor answers. If nothing listens on port 8321, start it in the background:
  `& "ROOT\.venv\Scripts\karaoke.exe" serve` (from ROOT, after reloading PATH). Then print STATUS CODES ONLY:
  ```powershell
  (Invoke-WebRequest http://127.0.0.1:8321/ -UseBasicParsing).StatusCode
  (Invoke-WebRequest http://127.0.0.1:8321/api/songs/<slug> -UseBasicParsing).StatusCode
  ```
- The song is in the library: `(Invoke-RestMethod http://127.0.0.1:8321/api/songs) | Where-Object id -eq '<slug>' | Select-Object id, words, flaggedWords`
  — `words` must equal `counts.words` in `report.json`.

### 5. Create the permission record

Check the current status first (the extra parentheses and `% { $_ }` unroll the JSON array in
Windows PowerShell 5.1; without them the filter silently matches nothing):
```powershell
(& "ROOT\.venv\Scripts\karaoke.exe" permissions --json | ConvertFrom-Json) | % { $_ } | ? song_id -eq '<slug>' | Select-Object song_id, status
```
If `<slug>` already has a status other than `Not asked`, leave it. Otherwise:
```powershell
& "ROOT\.venv\Scripts\karaoke.exe" permissions set <slug> --status "Not asked" [--artist "<artist, if the user named one>"]
```

### 6. Report in three lines

```
Stages: 5/5 passed (ingest, separate, translate, align, assemble) in <total> s.
To review: <flaggedWords> of <words> words (timing).
Editor: http://127.0.0.1:8321/#/song/<slug> (permission: Not asked)
```

On failure, report instead: the stage that stopped, the error message, and the likely fix:

| Stage | Typical error | Likely fix |
| --- | --- | --- |
| ingest | file not found / no Hebrew line | check the file names; lyrics need at least one Hebrew line |
| ingest | `[WinError 2]` | ffmpeg not on PATH: reload PATH (step 2) and rerun |
| ingest | song already exists | ask the user, then rerun with `--force` |
| separate | CUDA out of memory | close other GPU apps (Resolve, games) and rerun |
| align | model download or CUDA error | check the internet connection for a first download; close GPU apps |
| align | timing checkpoint failed | lyrics must list what is SUNG, one line per sung line, repeats included |
