# Maagal Karaoke Studio

Maagal Karaoke Studio is a desktop app for singing along with Hebrew lyrics. It opens its own window and works offline. The song library includes **Hatikva**, **Lecha Dodi** and **Shalom Aleichem**.

## Open the app

**Windows 10 or later, 64-bit.** Open `Maagal-Karaoke-Studio-Windows-Setup.exe` and choose **Install**. After installation, open **Maagal Karaoke Studio** from the Start menu. For a portable copy, extract `Maagal-Karaoke-Studio-Windows-x64.zip` into a folder and open **Karaoke IL.exe** inside it.

**Mac testers wanted.** The macOS source targets Apple silicon and Intel Macs. We need physical hardware tests before offering a Mac download. ScreenCaptureKit recording targets macOS 13 or later. [Volunteer or report a Mac test](https://github.com/maagalhebrew/maagal-karaoke-studio/issues/1).

[Download the Windows x64 prerelease](https://github.com/maagalhebrew/maagal-karaoke-studio/releases/tag/v2.0.0-beta.1). The installer is unsigned. Included songs play offline immediately. Automatic preparation requires a one-time timing-tool download in this public build. Recognition on choirs can produce incorrect lyrics and translations.

## Sing your first song

1. Choose **Play** beside a song. If it begins with a long instrumental introduction, **Skip to singing** takes you to the first words.
2. Follow the large Hebrew words. The amber underline marks the current word. **Text options** controls vowel points, pronunciation and English. Capital letters in the pronunciation mark the stressed syllable.
3. Choose **Backing only** to sing without the recorded voices. Use **Repeat line**, **Speed**, or the previous and next line controls to practise at your own pace.
4. To save a favorite or find the performers’ credits, open **Song tools**. The link to **MaagalHebrew.com** is in the song library.

## Bring your own recording

Choose **Add a song**, select an audio or video file, and paste the lyrics, one sung line per line. You can add an English translation after each lyric line. Use **Preview selection** and the start and end fields to choose an excerpt. With **Tap the words myself**, listen and mark each word, then save. Add pronunciation and update English under **Song tools → Pronunciation and English**.

Automatic word timing and voice separation are optional downloads for Windows x64 and Apple silicon. They require an internet connection for setup and run locally afterward. For choir recordings, check the result by singing along. You can correct individual words under **Song tools → Lyrics and timing**. Intel Macs support manual timing. A song you add with manual timing plays its original recording.

## Save and move songs

**Song tools → Save a copy** writes an editable song ZIP with its audio, timing, text and exercises. On the other computer, choose **Import a saved song** in the library. Earlier Karaoke IL song ZIPs use the same import action. A restored song with a matching name is saved as a separate copy.

Favorites and practice history stay with the local library. To back up your whole library, close the app and copy the **Karaoke IL** folder from `%LOCALAPPDATA%` on Windows or `~/Library/Application Support/` on Mac. Reinstalling the program uses that same library. Recordings a listener adds stay on their computer.

**Song tools → Clips and drills** saves selected phrases, repetitions, silent turns and teaching cards. **Export** can produce subtitles, a transparent caption overlay or a lesson video. Recording and arrangement credits travel with editable song copies. See the included [recording credits](desktop/catalog/CREDITS.txt).

## Development and packaging

The standalone entry point is `desktop/launch.py`. It uses native Qt Widgets and Qt Multimedia. It calls the local karaoke engine directly.

The Windows package builder uses Python 3.11, `pip`, `pefile` and Inno Setup 6. The Mac launcher build uses Zig 0.13. The Mac system audio helper needs Xcode with the macOS 13 or later SDK. Run `python desktop/build.py --mac-capture-only` on a Mac from the same revision and copy `.build/desktop/mac-capture/` into the Windows build checkout before packaging both Mac ZIPs. The Windows .NET Framework C# compiler builds the small GUI launcher. Set `ISCC` to the path to Inno Setup’s `ISCC.exe` if it is installed elsewhere. From the repository root, use 64-bit Windows Python 3.11 to stage the language packages.

```text
python -c "import struct, sys; assert sys.platform == 'win32' and sys.version_info[:2] == (3, 11) and struct.calcsize('P') == 8"
python -m pip install --no-deps --target .build/language-packages transformers==4.51.3 sentencepiece==0.2.1 sacremoses==0.1.1 phonikud==0.4.1 phonikud-onnx==1.0.6 colorlog==6.9.0 num2words==0.5.14 docopt==0.6.2
```

For a language-processing environment that also uses Joblib, stage the optional package with
`python -m pip install --no-deps --target .build/language-packages joblib==1.5.3`.

The standard Windows installer includes the reading models and Windows language
packages. Automatic separation and timing use an existing timing environment
or the one-time timing download from the app. The private installer below
includes a CPU timing environment and the local model weights.

From this repository, with the build environment active, run:

```text
python desktop/fetch_runtimes.py
python desktop/fetch_wheels.py
python desktop/fetch_native.py
python desktop/fetch_reading_models.py
python desktop/build.py
python desktop/build_installer.py
python desktop/verify.py
```

The packages and SHA-256 checksums are written to `release/`. The Mac ZIPs retain executable permissions and relative links. On a matching host, `python desktop/verify.py --native-smoke` exercises playback, text, import and restore with the bundled runtime and a clean library. On Windows, `python desktop/verify_installer.py` also exercises the real installer, launcher and Windows accessibility controls. That check uses `psutil` and `pywinauto`.

For a source run, make PySide6 6.8.3, the packages in `desktop/base-wheels.txt`, the additional packages in `desktop/windows-wheels.txt` on Windows, and FFmpeg and FFprobe available and run `python desktop/launch.py`. Use `KARAOKE_HOME` to select a separate test library.

### Private Windows QA

A development-only Windows ZIP can include an existing CPU timing environment
and verified model weights for offline testing. After staging the same reading
models and Windows language packages as above, point the builder to a Windows
x64 Python 3.11 CPU timing environment and its verified Hugging Face cache.

```text
python desktop/build.py --private-qa-python <timing-python.exe> --private-qa-hub <huggingface-hub>
python desktop/verify.py --private-qa --recording
```

The private ZIP and its checksum are under `release/private-qa/`. Keep this
archive private while model redistribution is under review. To build an
installer for the private archive, use the x64 Inno Setup 7 compiler and run
`python desktop/build_installer.py --private-qa --compiler <path-to-ISCC.exe>`.
Keep the generated `-PRIVATE-QA.exe` and its companion `.bin` file together
when opening the installer.
