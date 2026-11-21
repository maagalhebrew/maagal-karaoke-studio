"""Install the optional local timing tools only after a listener chooses Download."""
from __future__ import annotations

import hashlib
import os
import platform
import shutil
import ssl
import subprocess
import sys
import threading
import urllib.request
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from . import paths
from .models import WHISPER
from .text import LANGUAGES, check_language


# The revisions and SHA-256 sums identify the exact publisher files used by
# the original pipeline. A cache folder, lock file or partial transfer alone
# cannot enable automatic timing.
DEMUCS_REPO = "adefossez/HTDemucs"
REVISIONS = {
    DEMUCS_REPO: "cbc8a9b1a87023b7fd74e7b3412e6321c0eab003",
    WHISPER["he"]: "72ad623a37947395efcc3933132353790e5a12f5",
    WHISPER["es"]: "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf",
}
VOCAB = {
    "tokenizer.json": (2710337, "297b13372ac43916285644fb9687add3cc62ee2a1adb60da3dc25cc94c1871fd"),
    "vocabulary.json": (1068114, "c69260f2ab26d659b7c398f9a2b2b48ed0df16c3b47d7326782fd9cba71690c1"),
}
FILES = {
    DEMUCS_REPO: {
        "htdemucs.yaml": (21, "239c445d0b14454d541ad8bd9bb271c9e536d267e8a4625208744cbb2e7bb66c"),
        "955717e8.safetensors": (84025440, "d9fa14133cfcc034a6758923bb3a8ca9f8dfd0b582134643bbf83f72c17576dd"),
    },
    WHISPER["he"]: {
        **VOCAB,
        "config.json": (1405, "c805eff43fc2a1d00d5cfa315e4b2230895f34994257c185959808a116e7c4f0"),
        "preprocessor_config.json": (357, "654cf18d3e163b948ceaf9766da56ce0b52de265d58673cf61c9376f126bd499"),
        "model.bin": (1617884968, "db2a2265aa012c16c7db9edda3d699c99f984efdd3f2e22a72a8ce7e9720f3a2"),
    },
    WHISPER["es"]: {
        **VOCAB,
        "config.json": (2263, "b0253ea6c0d3bea6b1e19e91a02acfd3b53f4467362efcb5a3e6b16c9b3a9b7e"),
        "preprocessor_config.json": (340, "7ccc62c6f2765af1f3b46c00c9b5894426835a05021c8b9c01eecb6dfb542711"),
        "model.bin": (1617884929, "e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da"),
    },
}
PACKAGES = (
    "demucs==4.1.0", "sphn==0.2.1", "faster-whisper==1.2.1", "stable-ts==2.19.1",
    "transformers==4.51.3", "sentencepiece==0.2.1", "sacremoses==0.1.1",
    "phonikud==0.4.1", "phonikud-onnx==1.0.6",
    "openai-whisper==20250625", "ctranslate2==4.6.0", "huggingface-hub==0.36.0",
    "tokenizers==0.21.4", "numpy==2.2.6", "jsonschema==4.26.0",
)
PROBE = """
import sys
if sys.version_info[:2] != (3, 11):
    sys.exit(1)
from importlib.util import find_spec
if any(find_spec(name) is None for name in ('demucs', 'faster_whisper', 'stable_whisper', 'jsonschema')):
    sys.exit(1)
import torch, torchaudio, demucs.hf, jsonschema
from transformers import MarianMTModel, MarianTokenizer
from phonikud_onnx import Phonikud
from phonikud import phonemize
from demucs.separate import main
from stable_whisper import load_faster_whisper
from faster_whisper import WhisperModel
"""

# Windows extended-length paths support long names but do not expand ".." or
# translate "/" for the OS. Bundled pip 26.2.2 joins wheel RECORD entries such
# as "../../Scripts/numba" verbatim to its site-packages path when rehashing
# rewritten scripts. Normalize that one path inside this installer process.
WINDOWS_PIP = """
import os
from pip._internal.cli.main import main
from pip._internal.operations.install import wheel
original_path = getattr(wheel, "_record_to_fs_path", None)
if original_path:
    wheel._record_to_fs_path = lambda *args, **kwargs: os.path.normpath(original_path(*args, **kwargs))
raise SystemExit(main())
"""
_lock = threading.RLock()
_active: str | None = None
_message = ""
_errors: dict[str, str] = {}


def is_installing() -> bool:
    with _lock:
        return _active is not None


def _home() -> Path:
    # Source launches must also leave the installation read-only.
    if os.environ.get("KARAOKE_HOME"):
        return paths.HOME / "timing"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Karaoke IL/timing"
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local/share") / "Karaoke IL/timing"


def _venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _setup_path(path: Path) -> Path:
    """Give pip room for wheel members beyond Windows' default 260-character limit."""
    if os.name != "nt":
        return path
    value = str(path.absolute())
    if value.startswith("\\\\?\\"):
        return path
    if value.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + value[2:])
    return Path("\\\\?\\" + value)


def _pip_entry(venv: Path) -> list:
    """Use a regular Windows path for wheel installers whenever it has enough room."""
    if os.name != "nt" or len(str(venv)) <= 100:
        return [_venv_python(venv), "-I", "-B", "-m", "pip"]
    import ctypes

    # The longest path in the Windows torch wheel uses another 137 characters.
    # NTFS usually provides a short alias for an existing environment.
    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetShortPathNameW(str(_setup_path(venv)), buffer, len(buffer))
    if 0 < length < len(buffer):
        short = buffer.value
        if short.startswith("\\\\?\\UNC\\"):
            short = "\\\\" + short[8:]
        else:
            short = short.removeprefix("\\\\?\\")
        if len(short) <= 100:
            return [_venv_python(Path(short)), "-I", "-B", "-m", "pip"]
    # Some drives have short names disabled. Keep the extended path throughout
    # this process and normalize pip's RECORD entries before it opens them.
    return [_venv_python(_setup_path(venv)), "-I", "-B", "-c", WINDOWS_PIP]


def _base() -> Path:
    return Path(os.environ.get("KARAOKE_RESOURCE_PYTHON") or sys.executable)


def _hubs() -> tuple[Path, ...]:
    default_home = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "huggingface"
    system_hub = (os.environ.get("HF_HUB_CACHE") or os.environ.get("HUGGINGFACE_HUB_CACHE")
                  or Path(os.environ.get("HF_HOME") or default_home) / "hub")
    return tuple(dict.fromkeys((paths.ROOT / "models/hub", _home() / "hub", Path(system_hub))))


def _repo_dir(hub: Path, repo: str) -> Path:
    return hub / ("models--" + repo.replace("/", "--"))


@lru_cache(maxsize=128)
def _sha256(path: Path, size: int, modified: int, changed: int) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _valid(path: Path, expected: tuple[int, str]) -> bool:
    try:
        stat = path.stat()
        return stat.st_size == expected[0] and _sha256(path, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns) == expected[1]
    except OSError:
        return False


def _model_hub(language: str) -> Path | None:
    for hub in _hubs():
        for repo in (WHISPER[language], DEMUCS_REPO):
            location = _repo_dir(hub, repo)
            try:
                if (location / "refs/main").read_text(encoding="ascii").strip() != REVISIONS[repo]:
                    break
            except (OSError, UnicodeError):
                break
            snapshot = location / "snapshots" / REVISIONS[repo]
            if not all(_valid(snapshot / name, expected) for name, expected in FILES[repo].items()):
                break
        else:
            return hub
    return None


def _run(command: list, *, timeout: int, env: dict | None = None, log=None) -> subprocess.CompletedProcess:
    return subprocess.run(command, stdin=subprocess.DEVNULL, stdout=log if log else subprocess.DEVNULL,
                          stderr=subprocess.STDOUT if log else subprocess.DEVNULL,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=timeout, env=env)


@lru_cache(maxsize=16)
def _usable(exe: Path, modified: int) -> bool:
    try:
        probe = PROBE
        if (paths.ROOT / "processing-packages").is_dir():
            probe = "import site;site.addsitedir(" + repr(str(paths.ROOT / "processing-packages")) + ")\n" + PROBE
        return _run([exe, "-I", "-B", "-c", probe], timeout=70,
                    env={**os.environ, "HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1"}).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _runtime() -> Path | None:
    candidates = [_base(), _venv_python(_home() / "runtime-v1"), os.environ.get("KARAOKE_AUTOMATIC_PYTHON"),
                  _venv_python(paths.ROOT / ".venv")]
    if os.environ.get("VIRTUAL_ENV"):
        candidates.append(_venv_python(Path(os.environ["VIRTUAL_ENV"])))
    for candidate in dict.fromkeys(Path(p) for p in candidates if p):
        try:
            if _usable(candidate, candidate.stat().st_mtime_ns):
                return candidate
        except OSError:
            continue
    return None


def _supported() -> bool:
    machine = platform.machine().lower()
    return sys.version_info[:2] == (3, 11) and (
            (sys.platform == "win32" and machine in {"amd64", "x86_64"}) or
            (sys.platform == "darwin" and machine in {"arm64", "aarch64"}))


def status(language: str) -> dict:
    check_language(language)
    with _lock:
        if _active:
            return dict(manualAvailable=True, automaticReady=False, installing=True, canInstall=False, message=_message)
        error = _errors.get(language)
    ready = _model_hub(language) is not None and _runtime() is not None
    supported = _supported()
    if ready:
        message = f"Automatic timing for {LANGUAGES[language]} is ready on this computer."
    elif error:
        message = f"Automatic timing for {LANGUAGES[language]} still needs setup."
    elif supported:
        message = "Download the timing tools once to separate the singer and match the words. Your recordings stay on this computer."
    elif sys.platform == "darwin" and platform.machine().lower() == "x86_64":
        message = "This Intel Mac can use tap timing. The automatic timing download requires a Mac with Apple silicon."
    else:
        message = "You can set the timing yourself here. The desktop download includes automatic setup for 64-bit Windows PCs and Macs with Apple silicon."
    result = dict(manualAvailable=True, automaticReady=ready, installing=False, canInstall=supported and not ready,
                  message=message)
    if error and not ready:
        result["error"] = error
    return result


def python_for(language: str) -> Path:
    check_language(language)
    if _model_hub(language):
        python = _runtime()
        if python:
            return python
    raise RuntimeError("Download automatic timing for this language first, or choose tap timing.")


def bundled():
    return (paths.ROOT / "processing-packages").is_dir() and (paths.ROOT / "models/hub").is_dir()


def worker_env(language: str) -> dict[str, str]:
    check_language(language)
    hub = _model_hub(language)
    if not hub:
        raise RuntimeError("Download automatic timing for this language first, or choose tap timing.")
    return offline_env(hub)


def offline_env(hub):
    modules = [paths.ROOT / "backend"]
    if (paths.ROOT / "processing-packages").is_dir():
        modules.append(paths.ROOT / "processing-packages")
    return {"PYTHONPATH": os.pathsep.join(map(str, modules)), "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1", "HF_HUB_CACHE": str(hub), "HUGGINGFACE_HUB_CACHE": str(hub),
            "HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1", "TRANSFORMERS_OFFLINE": "1"}


def _progress(message: str) -> None:
    global _message
    with _lock:
        _message = message


@contextmanager
def _install_lock():
    """Release the OS lock on normal exit or interruption. All retries reuse verified files."""
    root = _home()
    root.mkdir(parents=True, exist_ok=True)
    with (root / "setup.lock").open("a+b") as stream:
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError("Another Karaoke IL window is setting up automatic timing. Try again after it finishes.") from None
        yield


def _install_runtime() -> None:
    _progress("Getting the timing tools ready. Keep Karaoke IL open.")
    root = _home()
    root.mkdir(parents=True, exist_ok=True)
    venv = root / "runtime-v1"
    python = _venv_python(venv)
    env = {key: val for key, val in os.environ.items()
           if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "__PYVENV_LAUNCHER__"} and not key.startswith("PIP_")}
    env.update(PIP_CONFIG_FILE=os.devnull, PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1")
    # Each attempt replaces the previous setup diagnostics. This file sees only
    # installation commands and import checks, never song processing.
    with open(root / "setup.log", "w", encoding="utf-8", opener=lambda p, flags: os.open(p, flags, 0o600)) as log:
        def check(command, timeout, message, failure):
            _progress(message)
            print(message, file=log, flush=True)
            try:
                code = _run(command, timeout=timeout, env=env, log=log).returncode
            except (OSError, subprocess.TimeoutExpired) as exc:
                print(f"{type(exc).__name__}: {exc}", file=log, flush=True)
                raise RuntimeError(failure) from None
            print(f"Exit {code}", file=log, flush=True)
            if code:
                raise RuntimeError(failure)

        check([_base(), "-I", "-B", "-m", "venv", str(_setup_path(venv))], 600,
              "Setting up the private timing folder.",
              "Karaoke IL could not create its timing folder. Check your free space and try again.")
        pip = [*_pip_entry(venv), "--disable-pip-version-check", "--no-input", "install", "--prefer-binary"]
        # Wheel build subprocesses also need this interpreter when the listener
        # has never installed Python or activated a development environment.
        env["PATH"] = str(pip[0].parent) + os.pathsep + env.get("PATH", "")
        index = "https://download.pytorch.org/whl/cpu" if sys.platform == "win32" else "https://pypi.org/simple"
        for packages, source, message in (
            (["torch==2.8.0", "torchaudio==2.8.0"], index, "Installing the audio engine. Keep Karaoke IL open."),
            (PACKAGES, "https://pypi.org/simple", "Installing the voice and timing tools. Keep Karaoke IL open."),
        ):
            check([*pip, "--index-url", source, *packages], 3600, message,
                  "The timing tools could not be installed. Check your internet connection and free disk space, then try again.")
        _usable.cache_clear()
        if not _usable(python, python.stat().st_mtime_ns):
            env.update(HF_HUB_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
            check([python, "-I", "-B", "-c", PROBE], 90, "Checking the timing tools.",
                  "The timing tools could not start on this computer. Try the download again or use tap timing.")
            _usable.cache_clear()


def _download(repo: str, name: str, target: Path, expected: tuple[int, str], language: str) -> None:
    partial = target.with_suffix(target.suffix + ".part")
    size = partial.stat().st_size if partial.exists() else 0
    if size == expected[0] and _valid(partial, expected):
        partial.replace(target)
        return
    if size >= expected[0]:
        size = 0
    headers = {"Range": f"bytes={size}-"} if size else {}
    request = urllib.request.Request(f"https://huggingface.co/{repo}/resolve/{REVISIONS[repo]}/{name}", headers=headers)
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=60, context=context) as response:
        if response.status != 206:
            size = 0
        elif not response.headers.get("Content-Range", "").startswith(f"bytes {size}-"):
            raise RuntimeError("The download stopped before it could resume. Try again.")
        with partial.open("ab" if size else "wb") as output:
            while data := response.read(1024 * 1024):
                output.write(data)
                size += len(data)
                if size > expected[0]:
                    raise RuntimeError("A download was larger than expected. Try again.")
                if expected[0] > 10_000_000:
                    label = "voice separation" if repo == DEMUCS_REPO else LANGUAGES[language] + " timing"
                    _progress(f"Downloading {label} · {size * 100 // expected[0]}%. Keep Karaoke IL open.")
    if not _valid(partial, expected):
        if size == expected[0]:
            partial.unlink()
        raise RuntimeError("The download was incomplete or damaged. Try again to finish it.")
    partial.replace(target)


def _install_models(language: str) -> None:
    managed, *others = _hubs()
    for repo in (DEMUCS_REPO, WHISPER[language]):
        model = _repo_dir(managed, repo)
        relative = Path("snapshots") / REVISIONS[repo]
        snapshot = model / relative
        snapshot.mkdir(parents=True, exist_ok=True)
        for name, expected in FILES[repo].items():
            target = snapshot / name
            if _valid(target, expected):
                continue
            candidates = (_repo_dir(hub, repo) / relative / name for hub in others)
            source = next((file for file in candidates if _valid(file, expected)), None)
            if source:
                temporary = target.with_suffix(target.suffix + ".part")
                shutil.copyfile(source, temporary)
                if not _valid(temporary, expected):
                    raise RuntimeError("The saved timing files changed while being copied. Try again.")
                temporary.replace(target)
            else:
                _download(repo, name, target, expected, language)
        # The pipeline opens the model by its official repo name in offline mode.
        refs = model / "refs"
        refs.mkdir(exist_ok=True)
        pending = refs / "main.part"
        pending.write_text(REVISIONS[repo], encoding="ascii")
        pending.replace(refs / "main")


def _install(language: str) -> None:
    global _active
    try:
        with _install_lock():
            if not _runtime():
                _install_runtime()
            if not _model_hub(language):
                _progress(f"Getting the {LANGUAGES[language]} timing files. Keep Karaoke IL open.")
                _install_models(language)
            python_for(language)
    except Exception as exc:
        message = str(exc) if isinstance(exc, RuntimeError) else (
            "The setup stopped. Check your internet connection and free disk space, then try again.")
        with _lock:
            _errors[language] = message
    finally:
        with _lock:
            _active = None


def start(language: str) -> dict:
    global _active, _message
    info = status(language)
    with _lock:
        if info["canInstall"] and not _active:
            _active = language
            _message = f"Preparing automatic timing for {LANGUAGES[language]}. Keep Karaoke IL open."
            _errors.pop(language, None)
            threading.Thread(target=_install, args=(language,), name="karaoke-timing-setup", daemon=True).start()
        if _active:
            return dict(manualAvailable=True, automaticReady=False, installing=True, canInstall=False, message=_message)
    return info
