# Run Maagal Karaoke Studio in the browser

This is the local version: a Python server on this computer and a web page at
`http://127.0.0.1:8321`. There is no installer and nothing is code-signed.

Your songs stay inside the folder you clone. Do not put that folder in
`C:\Users\agawr\Documents` or on the Desktop if those sync to Google Drive.
A normal place is fine, for example `C:\src\maagal-karaoke-studio`.

## 1. Install the tools (once)

In PowerShell:

```powershell
winget install Python.Python.3.11 OpenJS.NodeJS.LTS Gyan.FFmpeg Git.Git
```

Close and reopen PowerShell so `py`, `node`, `npm` and `ffmpeg` are on PATH.

Optional, for automatic English: install [Ollama](https://ollama.com), then:

```powershell
ollama pull gemma4:12b
```

The song still finishes if Ollama is off. You type the English yourself.

## 2. Clone

```powershell
git clone https://github.com/maagalhebrew/maagal-karaoke-studio.git
cd maagal-karaoke-studio
git checkout local-browser
```

Use this branch until it is merged. `main` is the native desktop installer.

## 3. Start

Double-click `start-local.bat`, or in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-local.ps1
```

The script:

- creates `.venv` with Python 3.11 if it is missing
- installs the CUDA 12.6 PyTorch build, then the libraries in `backend`
- runs `npm ci` and `npm run build` in `frontend` when `frontend\dist` is missing or older than the source
- starts the server on `127.0.0.1` port `8321` only
- opens that address in the browser

Keep the window open. Closing it stops the studio. The next launch skips the
installs when they are already there.

Lesson-video export also needs the Remotion project, once:

```powershell
cd render
npm ci
cd ..
```

## Models it expects

The editor does not list, name, or let you pick a model. The start script does not
download these. They are already cached on the laptop that was used before. A new
computer needs them the first time a song is processed.

| Job | Where | What the app uses |
| --- | --- | --- |
| English | local Ollama | always `gemma4:12b` |
| Separate voice and music | Demucs | `htdemucs` |
| Time the words | Hugging Face | Hebrew: `ivrit-ai/whisper-large-v3-turbo-ct2`. Spanish: `mobiuslabsgmbh/faster-whisper-large-v3-turbo`. The song's language decides. |

If Ollama is not running, or `gemma4:12b` is not installed, Add a song says that English
translation isn't available. The song can still be added; type the English in the editor.
There is no menu of other models.

`data\translate.json` turns English on or off and names `gemma4:12b`. A developer can
override that name by starting the server with `KARAOKE_TRANSLATE_MODEL` set. Neither
appears in the editor.

The app does not show vowel points as a setting, and it does not show a pronunciation
or transliteration line. Lyrics are shown as written. Matching still ignores vowel
marks internally. The unused niqqud model `dicta-il/dictabert-large-char-menaked` stays
unused. A copy already on the laptop is left unused.

To download the timing and separation weights on a machine that does not have them yet
(about 3.5 GB; not required to open the editor):

```powershell
.venv\Scripts\python.exe -c "from huggingface_hub import snapshot_download as d; d('ivrit-ai/whisper-large-v3-turbo-ct2'); d('mobiuslabsgmbh/faster-whisper-large-v3-turbo')"
.venv\Scripts\python.exe -c "from demucs.pretrained import get_model; get_model('htdemucs')"
```

Hugging Face weights usually sit in `%USERPROFILE%\.cache\huggingface`. Ollama keeps
its own model store. Those folders are outside this clone, so cloning does not
delete them and Git does not contain them.

## Where your songs live

With the defaults, everything is inside the clone:

| Path | What |
| --- | --- |
| `songs\<slug>\` | one folder per song: `song.json`, `audio\original.wav`, and when separation has run `audio\vocals.wav` and `audio\instrumental.wav`, plus `report.json` and `backups\` |
| `inbox\` | uploads and the lyrics file for a run in progress |
| `data\karaoke.db` | library, favorites, practice history, permission records, export log |
| `data\youtube-cookies.txt` | optional YouTube sign-in cookies, if you add them |
| `data\translate.json` | English on/off for a developer (this file is in Git). The editor does not show it. |
| `.venv\` | the Python environment |

A song saved by the desktop app opens and saves here too, including one that has only
`audio\original.wav` (it is marked `availableTracks`) and an optional recording credit.
A pronunciation note on a line is kept in `song.json` and is not shown.

`KARAOKE_HOME` can point the writable library at another folder. Leave it unset.
This app does not set it, and it does not use Documents or Desktop.

## What a clone does not bring back

These are gitignored, so they are not in GitHub and a fresh clone does not restore them:

- `songs\` (recordings, stems, timing, edits)
- `inbox\`
- `data\karaoke.db`
- `data\youtube-cookies.txt`
- `.venv\`, `frontend\node_modules\`, `frontend\dist\`, `render\node_modules\`
- model weight files if they were stored inside the clone (`.cache\`, `models\`, `hub\`, `*.safetensors`, `*.bin`, `*.pt`)

The old project folder `C:\Users\agawr\Para Fold\1 Projects\karaoke il` is empty, and
those songs were never committed. If the desktop installer was used, a copy of the
library may still be at `%LOCALAPPDATA%\Karaoke IL` (`songs` and `data\karaoke.db`).
This browser version does not look there. To use those songs here, copy each song
folder into this clone's `songs\`, and copy `karaoke.db` into this clone's `data\`
if you also want favorites, practice history and permission records.

## Checks

```powershell
.venv\Scripts\python.exe -m pytest tests -k "not full_pipeline"
```

The full pipeline test needs a recording and is skipped without one. Point it at a
local file with `KARAOKE_TEST_RECORDING` if you do not want the file in `inbox\`.
