# Windows desktop verification, 21 November 2026

The native source base is `f76ddea4d6cddc8e0f29c17e6142dc8d1e0bc3a2` on `codex/native-karaoke`, from the clean checkout. No Git remote was configured. The upgrade branch is `codex/maagal-karaoke-studio`. Its first patch is `8d157cd`. The full changed-file list for that patch is `desktop/native/window.py`.

## Upgrade and capture

- `python desktop/verify_upgrade.py --installed "<installed Karaoke IL directory>"` passed the old and new Qt window, profile, audio, and backup checks. A word at 24,007 ms, a favorite, 13 seconds of history and two repeats survived. Three decoded tracks matched their original hashes. Both an explicit home and a redirected default location were tested in one Windows account.
- Windows WASAPI loopback captured a generated 641 Hz signal from Qt on Realtek speakers, measured at 640.87 Hz. It also captured Chrome's alternating 987 Hz and 1,283 Hz signal in a 15.5-second, 48 kHz stereo WAV. No separate headphone output was exposed. Device changes, headphones and macOS still require hardware checks.
- `python -m pytest -q tests` ran against the worktree backend with the project's test environment. Result: 208 passed, eight skipped, five subtests passed. Six offscreen Prepare song regressions also ran in the bundled Qt interpreter. They exercised real Windows process-tree cancellation, retry, drop, Spanish manual import and subtitle clipping. Model inference was simulated in those lifecycle tests.

## Recording-only trials

Each test submitted 22 seconds of audio, Hebrew language, and empty lyrics. The worker generated original, vocals, backing, recognized words, pronunciation and English with Hugging Face and Transformers offline. Tests ran on a Windows 11 laptop, Intel Family 6 Model 154, 31.7 GiB RAM. Concurrent build activity and cache warmth differed between trials. Sampled peak RSS sums resident memory of worker processes at half-second intervals and can count shared pages twice.

| Source and configuration | Wall seconds | Peak tree RSS, decimal GB | Highlighted / recognized words | Lines with fallback / recognized lines |
|---|---:|---:|---:|---:|
| Hatikva, festival choir, CPU | 600.1 | 2.14 | 4/10 | 2/3 |
| Lecha Dodi, live ensemble, CPU | 160.1 | 2.03 | 6/6 | 0/4 |
| Shalom Aleichem, FJMC recording, CPU | 79.7 | 2.01 | 12/12 | 0/2 |
| Adon Olam, Irene Rosenfeld solo recording outside the library, CPU, 45–67 seconds | 112.8 | 2.01 | 14/14 | 0/2 |
| Hatikva, same choir excerpt, separate RTX 3050 6 GB CUDA test environment | 53.0 | 2.66 | 6/10 | 1/3 |

The choir trial misrecognized familiar words in the anthem, producing incorrect English and pronunciation. High highlighting coverage alone does not establish correct lyrics or accurate onsets. The packaged Windows runtime uses CPU Torch. The CUDA comparison used an existing development runtime and cannot establish performance of the installer on another GPU.

The two Whisper weight files together occupy about 3.24 GB, HTDemucs about 84 MB, and Hebrew reading assets about 788 MB. Model selection for public release remains open. Independent human word-onset annotations are needed to report the required 250 ms median and 600 ms p90. `tests/timing_benchmark.py` checks those thresholds and reports fallback coverage. Its synthetic example is only a harness test. `desktop/benchmark_prepare.py` measures a real recording using an installed Studio and a cleared audio file.

The unfamiliar solo fixture is credited to Irene Rosenfeld, CC BY-SA 3.0, private benchmark excerpt only. [Recording and license](https://commons.wikimedia.org/wiki/File:Irene_Rosenfeld_-_Adon_Olam.ogg). The other three recordings are identified in `desktop/catalog/CREDITS.txt`. Featured master permissions and human recognition checks are tracked in `docs/featured-recordings.md`.

A separate supplied-lyrics CUDA trial used the first three catalogue lines and their matching audio selection. It failed while loading the alignment model with a native memory-allocation error under concurrent packaging load. That run supplied no onset measurements. The passing recording-only trials above did not require the optional text.

The synchronized standard Windows Setup also passed an in-place file upgrade over an isolated copy of the installed legacy application. Its 7,432 installed files (1,407,352,947 bytes) matched the candidate ZIP by SHA-256. The actual replaced launcher opened the new native window against the old profile. The edited onset, favorite, practice history, two repeats and three decoded track hashes survived. Registered-account upgrade testing remains open. Separate installer shortcut fixtures verified that old owned links are replaced and unrelated links are preserved.

The private Windows x64 archive passed its digest and pinned-weight checks. With the packaged Python interpreter, an empty profile and offline model settings, the 23–45 second Hatikva selection produced three 22-second audio tracks plus English and pronunciation on all three recognized lines. The private setup executable is unsigned. Keep its companion data file in the same directory.

Final private Setup verification passed. All 16,091 extracted payload files matched their ZIP sizes and CRCs. The installed native window exposed all three starter songs to Windows UI Automation, played and paused Hatikva and switched to its backing. The offline playback, text display, editing, backup, restore, subtitle and reopen checks passed. The app opened without a browser child or listening TCP socket. The two installer files together occupy 5,520,725,357 bytes. The standard Windows installer is the public prerelease. The fully bundled QA installer remains private.
