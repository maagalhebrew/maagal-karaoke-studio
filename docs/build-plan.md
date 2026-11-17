# Maagal Karaoke Studio — build plan v2

Written 17 Nov 2026. It follows on from milestones M0–M6 in CLAUDE.md. The same working rules apply: one milestone
at a time, run the acceptance tests for real, stop for a go-ahead, and commit at the end of each milestone.

## Decisions made

| Decision | Detail |
| --- | --- |
| **Two caption lines** | Lyrics + English. The niqqud model and the transliteration line are dropped; the music carries the pronunciation. |
| **Languages** | Hebrew and Spanish, set per song. |
| **Raw lyrics** | Users paste lyrics as copied from any website. The app cleans them on this computer using the Lyrics Cleaner skill (`skills\lyrics-cleaner\SKILL.md`). Cleaning can only remove lines, never change a word. |
| **Spanish at install** | Spanish is part of the standard download but can be turned off: on first run it is ticked by default in "Choose your languages". It can also be added later from Settings. |
| **App form** | A Windows desktop app: a Tauri shell (Rust, about 10 MB) runs the existing React interface in its own window and starts the Python backend as a hidden helper program (a "sidecar"). The AI models stay in Python; there is no Rust rewrite. |
| **First platform** | Windows 10/11, 64-bit. An NVIDIA GPU is recommended; computers without one fall back to the CPU, slower. |
| **Distribution** | Downloads linked from maagalhebrew.com and aarongawronsky.com, hosted on one file host. |
| **Ships with** | The models (downloaded on first run, with checksums), an open-source license, third-party notices and a user agreement (the user is responsible for fair use). |

## Decisions still open (needed before the milestone shown)

1. **License for your own code** (M10): MIT, Apache-2.0 (recommended: permissive, with patent protection) or GPL-3.0 (improvements must stay open).
2. **Video export engine** (M11):
   - **Recommended: replace Remotion with ffmpeg + ASS subtitles.** With two lines of text, ffmpeg can draw the captions, the teaching cards and the transparent ProRes overlay on its own. That removes Node and headless Chrome (about 300 MB) and Remotion's licensing question. Remotion's free license covers individuals and companies of up to 3 people, so you'd have to check how it applies to an app given to the public.
   - Otherwise keep Remotion and confirm its terms for redistribution.
3. **English translation model** (M11): Gemma 12B (about 7 GB, best quality) or a smaller model (about 2–3 GB). Decide after a quality test on 5 Hebrew and 5 Spanish songs. The English step stays optional either way.
4. **App name and look** (M10):
   - The name, for example "Maagal Studio".
   - Apply the brand kit to the app chrome: navy `#080F16`/`#182D42`, off-white `#E1E1E1`, amber `#E0A458`, Nunito / Nunito Sans / Rubik.
   - Captions stay in Heebo unless you choose Rubik.
5. **Code signing** (M13): an OV certificate (roughly $200–400 a year) or Azure Trusted Signing (cheaper; check whether it accepts individuals in your country).

## Size budget (download)

| Part | Size | Ships as |
| --- | --- | --- |
| Tauri shell + app code | ~30 MB | installer |
| Portable Python + PyTorch (CUDA) + faster-whisper + Demucs | ~3 GB on disk, ~1.5 GB compressed | installer (moves to the first-run download if the installer would pass 2 GB) |
| ffmpeg (LGPL build) | ~80 MB | installer |
| Demucs htdemucs | ~80 MB | first run, always |
| Hebrew timing model (ivrit-ai whisper-large-v3-turbo, CT2) | ~1.6 GB | first run, always |
| Spanish timing model (multilingual whisper-large-v3-turbo, CT2) | ~1.6 GB | first run, ticked by default |
| English helper (llama.cpp server + model) | 2–7 GB | first run, optional |

Expected download: about 3.5 GB for Hebrew only, about 5 GB for Hebrew + Spanish, plus the English helper if chosen.

---

## M7 — Two lines: remove niqqud and transliteration (schema 2)

Goal: the pipeline goes from seven stages to five (ingest, separate, translate, align, assemble), and every song uses
the new data format.

**Data format (schema 2), introduced once, here**
- Word: `{id, plain, startMs, endMs, confidence, flags}`. `pointed` and `syllables` are removed. `plain` keeps the
  text exactly as pasted (vowel points too, if the user supplied them).
- Song: add `language` (`"he"` | `"es"`). Every existing song is `"he"`.
- Drill step `tiers`: `["lyrics", "en"]`. `"he"` becomes `"lyrics"` and `"translit"` is dropped.
- Flags removed: `stress-guess`, `no-niqqud`, `niqqud-mismatch`, `non-hebrew`.
- Migration:
  - A `migrate_v1()` function in `songfile.py` runs whenever an old song.json is read, so old backups still load.
  - A `karaoke migrate` command converts every song on disk, keeping the old file in `backups\`.
  - Remove `showNiqqud` and `translitScale` from `data/presets.json`, and retire `data/overrides.json`.

**Backend**
- `stages.py`:
  - Remove the `niqqud` and `transliterate` stages, `MENAKED`, `_menaked_predict` and `given_syllables`.
  - Keep only the "timing" review group.
- Delete `translit.py`, `/api/translit` and `/api/overrides`, and the stress handling in `api.py` and `wordedit.py`.
- Keep `hebrew.strip_niqqud`. Matching still uses it, so lyrics pasted with vowels still line up with the singing.
- Remove `transformers` from `backend/pyproject.toml`; nothing else uses it.
- Lyrics parser: the three-line ChatGPT format becomes lyrics + English. Accept a third line but ignore it, so old files still import.
- `translate.py`: remove the transliteration wording from the prompts.
- `subtitles.py` / `export.py`:
  - Write one SRT per line (lyrics, en).
  - In the ASS file, move the word-by-word karaoke fill (`\kf`) onto the lyrics line; today it is only on the transliteration line.

**Frontend and render**
- Remove from the Studio editor:
  - the Stress card, syllable input, stress menu and "Show transliteration" toggle;
  - the Breakdown and Review uses of transliteration;
  - the "Add vowel points" and "Transliteration" step labels.
- The word panel's "Hebrew with vowel points" box becomes a plain "Word" text edit, with the same letters check.
- Keep a "Show vowel points" toggle, shown only when a song's text has any.
- Captions, Practice, the drill builder's tier checkboxes and the Remotion compositions show two lines.
- Update `skills/chatgpt-lyrics-skill.md` to the two-line format.

**Docs and tests**
- CLAUDE.md:
  - Update the tiers, the pipeline, the stack table, the data model and the M1 translit tests.
  - Record the decision: "transliteration dropped 17 Nov 2026".
- Delete `tests/test_translit.py`; update `test_api`, `test_pipeline` and `test_export`.
- Add a migration test on a synthetic v1 song: it has drills that include `translit`, and its backups still load.
- Drop the menaked check from `tests/m0_check.py`.

**Acceptance tests**
- [ ] All 11 existing songs migrate. Report counts only (songs, words, drills changed), never lyric text. Each opens in the Studio editor, and its drills still play.
- [ ] Hatikvah runs through all 5 stages, and the niqqud model never loads (checked from the GPU memory log).
- [ ] The SRT files contain exactly the lyrics and English lines, and the ASS file fills word by word on the lyrics line.
- [ ] The full test suite passes.

## M8 — Spanish songs

**Language everywhere**
- Add a song: a **Hebrew / Spanish** choice, remembered between songs. It is hidden when only one language pack is installed.
- `hebrew.py` → `text.py` with language-aware helpers:
  - `letters(word, lang)` keeps Spanish letters with their accents, plus ñ and ü, so "está" and "esta" stay different words;
  - `has_lyrics_text(line, lang)`.
  - Used by the ingest checkpoint ("at least one lyric line"), the importer's checks and the learning stats (vocabulary, "new to you", difficulty).
- **Lyrics parser:** Spanish and English share an alphabet, so the parser can't spot the English lines by script.
  - Add a "Format" choice on import: "lyrics only" or "each lyric line followed by its English".
  - For Hebrew it is guessed as today; for Spanish it must be chosen.
  - Add Spanish section words to `KINDS`: verso, estrofa, coro, estribillo, precoro, puente, intro, final.
- **Privacy guard** (`stages.py` ~615): today it hides an error message only if it contains Hebrew. Change it to hide any text that matches the song's lyrics, in either language.
- **Writing direction:** one `dirOf(language)` helper, used in Captions (including the wipe direction), LineList, WordInspector, FlagsPanel, BreakdownPanel and SuggestionsBox. `subtitles.py` adds right-to-left marks for Hebrew only.

**Models**
- New `backend/karaoke/models.py`: one registry of every model (id, language, size, sha256, license, required/optional). `stages.py`, `m0_check.py` and the model manager (M11) all read it.
- Align: choose the timing model and `language=` from `song.language`:
  - `he` → `ivrit-ai/whisper-large-v3-turbo-ct2`;
  - `es` → a CT2 build of `openai/whisper-large-v3-turbo` (check the exact repo id and license on Hugging Face first).
- Translation:
  - `translate.py` prompts per language, Hebrew → English and Spanish → English.
  - The "lyrics copied back as English" check works per language.
  - The word Breakdown prompt gets a Spanish version (verb forms, pronoun clitics), or is hidden for Spanish in v1.
- Permission request draft: one template per language (he, es), filled from Settings (see M10).

**Test fixture:** a traditional Spanish folk song in the public domain (for example "De Colores"), saved to
`tests\fixtures\de-colores\lyrics.txt`. You supply the recording for private local testing, as with Hatikvah.

**Acceptance tests**
- [ ] The Spanish song goes from Add a song to the Studio editor: left-to-right captions, English filled in, timing within the flag thresholds.
- [ ] Hatikvah gives the same timing as before M8 (regression check).
- [ ] An error during a Spanish import shows no lyric text in the terminal or logs.
- [ ] Learning stats ("new to you", difficulty) work for the Spanish song.

## M9 — Paste raw lyrics: the Lyrics Cleaner

Goal: the user pastes lyrics exactly as copied from any lyrics website, credits, ads, labels and all. The app cleans
them on this computer, following `skills\lyrics-cleaner\SKILL.md`, and shows what it removed before the song is
added. Lyrics never leave the machine (CLAUDE.md rule 5).

**How cleaning works: it can only delete, never rewrite**

The skill says to keep the lyrics "exactly as written". A language model asked to rewrite text sometimes "fixes" a
word, so the model never returns text:
1. **Rule pass (no model, instant)**, `backend/karaoke/clean.py`:
   - removes links, emails, the credits line patterns ("Written by", "Produced by", "מילים:", "לחן:", "Letra:", "Música:" and similar);
   - removes "Embed", "You might also like", "See … Live" and ad lines, placeholders (`[?]`, `(?)`, `[…]`), and dividers (`---`, `***`);
   - collapses runs of blank lines into one.
   - Section labels (`[Chorus]`, a bare "פזמון", "Coro:") are removed from the text but **kept as section hints**, so the chorus is still marked as a chorus. A label is not a lyric, so the cleaned text still follows the skill.
2. **Model pass (optional, local)**:
   - The lines that remain are sent, numbered, to the local English helper model (Ollama now, the bundled llama-server from M11).
   - The skill's text is the instruction, and the model must answer with **only the line numbers to remove**.
   - The app deletes those lines from the original. Any number that doesn't exist is ignored, and the model's output is never used as lyrics.
   - Without the helper installed, the rule pass alone runs.
3. **Safety checks:**
   - Every output line must be an exact line of the input, in the same order; a test enforces this.
   - If the model would remove more than 40% of the lines, or any line with 3 or more Hebrew or Spanish words, those removals are shown as "unsure" for the user to confirm instead of applied.

**Add a song**
- One "Lyrics" box takes the raw paste; the separate "already clean" path goes away.
- The language choice (from M8) tells the cleaner which credit words to look for.
- A **"Cleaned: kept 38 lines, removed 12"** panel lists the removed lines. Click a line to put it back; "unsure" removals come first.
- The lyrics check (line, section and word counts) runs on the cleaned text. Add song stays disabled while "unsure" lines are waiting for a decision.
- `skills\chatgpt-lyrics-skill.md` is retired: you no longer need ChatGPT to prepare lyrics. The parser still accepts the two-line lyrics + English format if pasted.

**Privacy**
- The cleaner logs counts only (lines kept, removed, unsure, by rule).
- The removed lines appear only in the app window, never in the terminal, logs or `report.json`.

**Acceptance tests**
- [ ] Unit tests on synthetic raw pastes (made-up text plus real-looking credits and ads; no copyrighted lyrics in the repo) in Hebrew, Spanish and English layouts:
  - all non-lyric lines removed;
  - every remaining line identical to the input;
  - repeats and ad-libs kept;
  - label lines turned into section hints.
- [ ] A model reply that tries to rewrite text, or names lines that don't exist, changes nothing beyond deleting real lines.
- [ ] With the helper off, the rule pass alone cleans a typical lyrics-site paste. On your own pastes, report counts only, no lyric text.
- [ ] Putting a removed line back, then adding the song, includes that line in the right place.

## M10 — Public build: personal data out, Maagal branding, licenses and agreement

**Personal data out**
- New Settings screen, "About you": name, channel name, contact. The permission request drafts use these. Remove from the code and tests:
  - the owner's name, city and phone number in `permissions.py` (`DRAFT`);
  - the same text in `tests/test_permissions.py`.
- CLAUDE.md, the `skills\` folder and `tests\m0_check.py` stay out of the shipped app (they are developer files). `m0_check` stops asserting the RTX 3050.
- `data/translate.json`: remove the personal `_note`. New installs start with empty data: no overrides, no songs, no database.
- Add a release check script that searches the shipped folders for personal strings and fails the build if any are found.

**Branding**
- Maagal theme from the brand kit; app icon from the small-size medallion; the medallion and the trace animation on the first-run and preparation screens.
- The B2 medallion loader on the splash while the backend starts. Use the brand kit files as they are (`maagal-brand-kit\logos`, `animations`, `loaders`).

**Licenses and agreement**
- A `LICENSE` file for your code (open decision 1).
- `THIRD_PARTY_NOTICES`, generated at build time: `pip-licenses` for Python, `license-checker` for npm, plus a hand-kept table of model licenses.
- An "About" screen with the version and the licenses.
- User agreement:
  - the text: for personal study and teaching; the user is responsible for copyright and fair use; the excerpt guard's thresholds are working rules, not legal advice;
  - shown on the installer's license page **and** on a first-run screen that must be accepted;
  - the accepted version and date are stored, and the user is asked again if the text changes.
- Have a lawyer review the agreement once (Israeli and US law).

**Acceptance tests**
- [ ] The release check finds no personal strings in the build output.
- [ ] A fresh profile cannot reach the app until the agreement is accepted; after acceptance it doesn't ask again until the text changes.
- [ ] The About screen lists every bundled library, tool and model with its license.

## M11 — Self-contained runtime and model manager

**Runtime**
- `build\runtime.ps1` builds a portable runtime:
  - Python 3.11 from python-build-standalone;
  - packages installed from a lock file (generated with `uv lock` or `pip-compile`), with PyTorch cu126;
  - an LGPL ffmpeg build.
- Nothing is taken from the user's PATH.
- Video export follows open decision 2 (ffmpeg engine recommended; otherwise bundle a portable Node, the render `node_modules` and Remotion's headless Chrome).

**English helper**
- Replace the Ollama requirement with a bundled `llama-server` (llama.cpp), which offers the same kind of local API.
- `translate.py` talks to it. Ollama stays usable as a setting for anyone who already has it.

**Folders**
- `paths.py` stops assuming the repo folder:
  - program files in the install folder;
  - models in `%LOCALAPPDATA%\Maagal Studio\models`;
  - songs and the database in `Documents\Maagal Studio`.
- A `KARAOKE_HOME` setting keeps today's layout for development.

**Model manager**
- `karaoke models list | download | verify`, with matching API endpoints.
- Downloads resume after an interruption and check sha256.

**First-run screen ("Getting everything ready")**
- Choose your languages: **Hebrew** (always), **Spanish** (ticked by default), English helper (optional).
- Shows sizes, a progress bar and the medallion animation.
- Settings → Languages adds or removes a pack later.

**GPU check**
- Detects CUDA. Without it, a clear notice explains that processing will take longer (with an estimate) and runs on the CPU.

**Acceptance tests**
- [ ] On a second Windows user account with no Python, Node, ffmpeg or Ollama on PATH, a song is added from start to finish.
- [ ] With Spanish unticked, no Spanish model is downloaded, and Add a song offers "Add Spanish" instead of the language choice.
- [ ] Unplugging the network mid-download, then reconnecting, resumes the download, and checksums pass.

## M12 — Desktop app (Tauri)

**Shell (`desktop\`, Tauri v2)**
- The Maagal window and icon, and the splash while the backend starts.
- Starts the sidecar (`runtime\python -m karaoke serve --port 0`, which reports its port back) and stops it on quit.
- Only one copy of the app runs at a time; outside links open in the browser.

**Installer**
- NSIS, installed per user (no admin rights needed), with the user agreement on its license page.
- Uninstalling asks whether to keep songs and models.

**Updates**
- The Tauri updater, signed with an updater key.
- The app code, the runtime and the models are versioned separately, so most updates are small. The runtime is replaced only when the lock file changes; models only when the registry changes.

**Acceptance tests**
- [ ] Install, first run, add a song, open the Studio editor, export a lesson: all without a terminal.
- [ ] Updating from one version to the next keeps songs, settings and models.
- [ ] Quitting the app leaves no Python or llama-server process running.

## M13 — Release

**Signing and hosting**
- Code signing (open decision 5) for the installer and the app.
- Hosting on GitHub Releases (2 GB per file) or Cloudflare R2 (no fees for downloads):
  - the installer;
  - the model files, or links to their Hugging Face sources where the license allows;
  - `latest.json` for the updater;
  - SHA-256 checksums.

**Download pages (on both websites)**
- System requirements:
  - Windows 10/11 64-bit;
  - an NVIDIA GPU with 6 GB or more recommended;
  - about 15 GB free disk.
- A link to the agreement and the licenses.
- The checksum and a "what's new" section.

**Clean-machine tests**
- One PC with an NVIDIA GPU and one without, neither a development machine.

**Acceptance tests**
- [ ] Download from both websites, install on the second PC, then take Hatikvah and a Spanish song each to a working drill in under 30 minutes of hands-on time.
- [ ] A signed installer: SmartScreen shows the publisher name, not "unknown publisher".
- [ ] An update published to the host reaches the installed app.

---

## Licenses to verify before shipping the models (M11)

| Component | Expected license | Status |
| --- | --- | --- |
| Demucs (htdemucs) | MIT | verify |
| ivrit-ai whisper-large-v3-turbo (CT2) | check the model card | **verify** |
| openai whisper-large-v3-turbo + the CT2 conversion | MIT (original); check the conversion's repo | verify |
| PyTorch, CTranslate2, faster-whisper, stable-ts | BSD / MIT | verify |
| NVIDIA CUDA DLLs inside the torch wheels | NVIDIA redistribution terms | verify |
| ffmpeg | LGPL (choose an LGPL build) | verify the build's configuration |
| Gemma / the chosen English model | Gemma terms or the model's own | **verify** |
| llama.cpp | MIT | verify |
| Heebo, Nunito, Rubik fonts | Open Font License | verify |
| Remotion (only if kept) | free for individuals / up to 3 people; app redistribution unclear | **verify, or replace** |

## Risks

- **Spanish timing quality.** The multilingual Whisper isn't tuned for singing either. Expect the same flagged words as with Hebrew; tap-to-time stays the fix.
- **Installer size.** If the runtime pushes the installer past 2 GB, PyTorch moves into the first-run download too.
- **CPU-only users.** Separation and timing can take 20–40 minutes per song. Say so on the download page.
- **Two models in GPU memory.** The rule of one model at a time (CLAUDE.md rule 4) still applies; the English helper must be unloaded before Whisper loads.
- **Agreement and fair use.** The tool can't decide fair use for the user. The excerpt guard and the agreement inform and log; they don't make it legal.

## Order and rough size

| Milestone | Size | Depends on |
| --- | --- | --- |
| M7 Two lines + schema 2 | M | — |
| M8 Spanish | M | M7 |
| M9 Paste raw lyrics (Lyrics Cleaner) | S–M | M8 (the language choice) |
| M10 Public build + branding + agreement | S–M | M7 (can run alongside M8–M9) |
| M11 Runtime + model manager | L | M9, M10 |
| M12 Tauri desktop app | M | M11 |
| M13 Release | S, plus waiting on the signing certificate | M12 |

**Done:** someone with no technical setup downloads Maagal Studio from either website, picks their languages, and
turns a favourite Hebrew or Spanish song into a working drill in under 30 minutes.
