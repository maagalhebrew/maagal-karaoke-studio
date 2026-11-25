# Maagal Karaoke Studio

This is a free tool by Aaron Gawronsky, creator of www.MaagalHebrew.com

A local Windows app that turns a Hebrew or Spanish song into an editable lesson. It separates the voice from the
music, times every word to the singing, adds English, and gives you a Studio editor, Practice mode, drills
and lesson-video export. Everything runs on your own computer: songs and lyrics never leave it.

Shared privately for testing: please don't redistribute. It has no license yet.

## What you need

- Windows 10 or 11 (64-bit)
- An NVIDIA graphics card, ideally 6 GB or more (it also works on the CPU, much more slowly)
- Python 3.11, Node.js 24 LTS, ffmpeg and Git on your PATH. With winget:
  ```powershell
  winget install Python.Python.3.11 OpenJS.NodeJS.LTS Gyan.FFmpeg Git.Git
  ```
- About 10 GB free disk for the AI models and libraries
- Optional, for automatic English: [Ollama](https://ollama.com) with a model such as `gemma4:12b`
  (`ollama pull gemma4:12b`). Without it, songs still work and you type the English yourself.

## Set up (once)

In PowerShell, inside the folder you cloned:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
# PyTorch with CUDA 12.6 (must be the cu126 build)
.venv\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126
.venv\Scripts\python.exe -m pip install -e "backend[dev]"
```

Download the AI models (about 3.5 GB; the app works offline after this):

```powershell
.venv\Scripts\python.exe -c "from huggingface_hub import snapshot_download as d; d('ivrit-ai/whisper-large-v3-turbo-ct2'); d('mobiuslabsgmbh/faster-whisper-large-v3-turbo')"
.venv\Scripts\python.exe -c "from demucs.pretrained import get_model; get_model('htdemucs')"
```

Build the editor:

```powershell
cd frontend; npm ci; npm run build; cd ..
cd render; npm ci; cd ..    # only needed for lesson-video export
```

Check everything is in place (GPU, models, Git):

```powershell
.venv\Scripts\python.exe tests\m0_check.py
```

## Use it

Double-click `start-local.bat` (or run `start-local.ps1`) in the clone. The first run creates `.venv`,
installs the Python libraries, builds the editor if `frontend\dist` is missing, starts the local server and
opens http://127.0.0.1:8321. Exact steps, the models it expects, and where your songs live are in
[RUN-LOCALLY.md](RUN-LOCALLY.md).

If the environment is already set up, `start-studio.ps1` only starts the server and opens the browser.
Keep that window open; closing it stops the studio. Then:

1. **Add a song**: record the computer's sound while the song plays, or pick an audio file.
2. Choose **Hebrew** or **Spanish** and paste the lyrics: one sung line per line, repeats written out, a blank
   line between sections.
3. About 5 minutes later the **Studio editor** opens. Play it, fix any word timing that's off (double-click a
   word), make sections, clips and drills, and practise.

Your songs live in `songs\` inside this clone, and uploads in `inbox\`. The library database is
`data\karaoke.db`. All three stay on your computer and are not added to Git. Do not put the clone in
Documents or Desktop if those folders sync to Google Drive.

## Good to know

- The permission-request draft is a short Hebrew or Spanish note filled in with the contact and the song title.
  The wording is in `backend\karaoke\permissions.py`.
- Tests: `.venv\Scripts\python.exe -m pytest tests -k "not full_pipeline"`
- `CLAUDE.md` is the project spec and working notes. `docs\build-plan.md` is the plan for what comes next.
