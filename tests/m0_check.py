"""M0 acceptance tests: environment, GPU, cached models, Git.

Run: .venv\\Scripts\\python.exe tests\\m0_check.py
Models load one at a time and are freed before the next (CLAUDE.md rule 4).
Hugging Face is forced offline, so a pass proves the models are cached locally.
"""
import gc
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from karaoke.models import WHISPER  # noqa: E402  (model ids live in one place)

results = []


def check(name, fn):
    try:
        detail = fn()
        results.append((True, name, detail))
        print(f"PASS  {name}: {detail}")
    except Exception as e:
        results.append((False, name, f"{type(e).__name__}: {e}"))
        print(f"FAIL  {name}: {type(e).__name__}: {e}")


def version_of(cmd, pattern):
    exe = shutil.which(cmd[0])
    if not exe:
        raise RuntimeError(f"{cmd[0]} not on PATH")
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    return re.search(pattern, out).group(0)


def free_gpu():
    import torch
    gc.collect()
    torch.cuda.empty_cache()


# --- Tools -----------------------------------------------------------------
def python_311():
    assert sys.version_info[:2] == (3, 11), sys.version
    return f"{sys.version.split()[0]} (venv: {sys.prefix})"


def node_lts():
    v = version_of(["node", "--version"], r"v\d+\.\d+\.\d+")
    assert int(v[1:].split(".")[0]) >= 24, v
    return v


check("Python 3.11", python_311)
check("Node.js 24 LTS", node_lts)
check("ffmpeg", lambda: version_of(["ffmpeg", "-version"], r"ffmpeg version \S+"))
check("Git", lambda: version_of(["git", "--version"], r"git version \S+"))


# --- PyTorch + CUDA -----------------------------------------------------------
def torch_cuda():
    import torch
    assert torch.cuda.is_available(), "torch.cuda.is_available() is False"
    name = torch.cuda.get_device_name(0)
    vram = torch.cuda.get_device_properties(0).total_memory / 2**30
    return f"torch {torch.__version__}, is_available=True, {name}, {vram:.1f} GB"


check("PyTorch CUDA", torch_cuda)


# --- Models (one at a time on the GPU) --------------------------------------
def demucs_model():
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model
    model = get_model("htdemucs").cuda().eval()
    try:
        audio = torch.zeros(1, 2, 44100 * 2, device="cuda")  # 2 s stereo silence
        with torch.no_grad():
            out = apply_model(model, audio, device="cuda", progress=False)
        return f"htdemucs on GPU, separated 2 s -> stems {model.sources}, shape {tuple(out.shape)}"
    finally:
        del model
        free_gpu()


def whisper_model(language):
    from faster_whisper import WhisperModel
    model = WhisperModel(WHISPER[language], device="cuda", compute_type="float16")
    try:
        import numpy as np
        segments, info = model.transcribe(np.zeros(16000, dtype=np.float32), language=language)
        list(segments)
        return f"loaded offline on GPU (float16), ran 1 s test, language={info.language}"
    finally:
        del model
        free_gpu()


check("Demucs htdemucs cached", demucs_model)
check("Hebrew timing model (ivrit.ai Whisper, CT2) cached", lambda: whisper_model("he"))
check("Spanish timing model (multilingual Whisper turbo, CT2) cached", lambda: whisper_model("es"))


# --- Git ----------------------------------------------------------------------
def git_repo():
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout.strip()
    assert Path(top).resolve() == ROOT, top
    must_ignore = [".venv/x", "songs/x/song.json", "inbox/x.mp3", "data/karaoke.db",
                   ".cache/x", "models/x.pt"]
    must_keep = ["CLAUDE.md", "tests/m0_check.py"]
    ignored = subprocess.run(["git", "check-ignore", *must_ignore, *must_keep], cwd=ROOT,
                             capture_output=True, text=True).stdout.split()
    missing = [p for p in must_ignore if p not in ignored]
    wrong = [p for p in must_keep if p in ignored]
    assert not missing and not wrong, f"not ignored: {missing}; wrongly ignored: {wrong}"
    return f"repo at {top}; ignores {len(must_ignore)}/{len(must_ignore)} required paths"


check("Git repo + .gitignore", git_repo)

passed = sum(ok for ok, _, _ in results)
print(f"\nM0: {passed}/{len(results)} checks passed")
sys.exit(0 if passed == len(results) else 1)
