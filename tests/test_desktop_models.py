"""The optional timing download never touches a recording or the base interpreter."""
import hashlib
import io
import os
import subprocess
import threading
from functools import lru_cache
from pathlib import Path

import pytest

from karaoke import desktop_models as models


@pytest.fixture
def setup(tmp_path_factory, monkeypatch):
    tmp_path = tmp_path_factory.mktemp("packs")
    home = tmp_path / "timing"
    hubs = (home / "hub", tmp_path / "existing")
    binary = b"word timing"
    files = {repo: {"weights": (len(binary), hashlib.sha256(binary).hexdigest())} for repo in models.REVISIONS}
    monkeypatch.setattr(models, "FILES", files)
    monkeypatch.setattr(models, "REVISIONS", {repo: "aa01" for repo in files})
    monkeypatch.setattr(models, "_home", lambda: home)
    monkeypatch.setattr(models, "_hubs", lambda: hubs)
    monkeypatch.setattr(models, "_supported", lambda: True)
    monkeypatch.setattr(models, "_runtime", lambda: Path("existing-python"))
    monkeypatch.setattr(models, "_errors", {})
    monkeypatch.setattr(models, "_active", None)
    return hubs, binary


def seed(hub, repo, binary):
    root = models._repo_dir(hub, repo)
    snapshot = root / "snapshots" / models.REVISIONS[repo]
    snapshot.mkdir(parents=True)
    (snapshot / "weights").write_bytes(binary)
    (root / "refs").mkdir()
    (root / "refs/main").write_text(models.REVISIONS[repo], encoding="ascii")
    return snapshot / "weights"


def test_setup_reads_the_chosen_language_and_rejects_corruption(setup):
    (managed, existing), binary = setup
    seed(existing, models.DEMUCS_REPO, binary)
    weights = seed(existing, models.WHISPER["he"], binary)
    assert models.status("he")["automaticReady"]
    assert not models.status("es")["automaticReady"]
    assert models.python_for("he") == Path("existing-python")
    env = models.worker_env("he")
    assert env["PYTHONPATH"] == str(models.paths.ROOT / "backend")
    assert env["HF_HUB_CACHE"] == str(existing) and env["HF_HUB_OFFLINE"] == "1"
    weights.write_bytes(b"x" * len(binary))
    os.utime(weights, (1, 1))
    assert not models.status("he")["automaticReady"]
    with pytest.raises(RuntimeError):
        models.python_for("he")
    for operation in (models.status, models.start, models.worker_env, models.python_for):
        with pytest.raises(ValueError):
            operation("../es")
    assert not managed.exists()


def test_download_verifies_bytes_and_resumes_the_partial(setup, monkeypatch, tmp_path):
    _, binary = setup
    target = tmp_path / "weights"
    repo = models.WHISPER["es"]
    expected = models.FILES[repo]["weights"]
    class Reply(io.BytesIO):
        status = 206
        headers = {"Content-Range": f"bytes 4-{len(binary) - 1}/{len(binary)}"}
    def response(request, **kwargs):
        assert request.full_url == f"https://huggingface.co/{repo}/resolve/{models.REVISIONS[repo]}/weights"
        assert request.headers["Range"] == "bytes=4-"
        return Reply(binary[4:])
    monkeypatch.setattr(models.urllib.request, "urlopen", response)
    target.with_suffix(".part").write_bytes(binary[:4])
    models._download(repo, "weights", target, expected, "es")
    assert target.read_bytes() == binary
    target.with_suffix(".part").write_bytes(b"xxxx")
    with pytest.raises(RuntimeError, match="damaged"):
        models._download(repo, "weights", target, expected, "es")
    assert target.read_bytes() == binary and not target.with_suffix(".part").exists()


def test_explicit_setup_reports_retriable_failure_then_reuses_files(setup, monkeypatch):
    (managed, existing), binary = setup
    seed(existing, models.DEMUCS_REPO, binary)
    entered, finish = threading.Event(), threading.Event()
    threads = []
    create_thread = threading.Thread
    def thread(**kwargs):
        item = create_thread(**kwargs)
        threads.append(item)
        return item
    monkeypatch.setattr(models.threading, "Thread", thread)
    def interrupted(*args):
        entered.set()
        assert finish.wait(5)
        raise OSError("connection closed")
    monkeypatch.setattr(models, "_download", interrupted)
    assert models.status("es")["canInstall"] and not threads
    assert models.start("es")["installing"] and entered.wait(5)
    assert models.start("he")["installing"] and len(threads) == 1
    finish.set()
    threads[0].join(5)
    assert models.status("es")["error"] and models.status("es")["canInstall"]
    def download(repo, name, target, expected, language):
        assert repo == models.WHISPER["es"] and language == "es"
        target.write_bytes(binary)
    monkeypatch.setattr(models, "_download", download)
    models.start("es")
    threads[-1].join(5)
    assert models.status("es")["automaticReady"] and "error" not in models.status("es")
    assert models.worker_env("es")["HF_HUB_CACHE"] == str(managed)
    assert not models.status("he")["automaticReady"]


def test_intel_mac_offers_tap_timing(monkeypatch):
    monkeypatch.setattr(models.sys, "platform", "darwin")
    monkeypatch.setattr(models.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(models, "_model_hub", lambda lang: None)
    result = models.start("es")
    assert result["manualAvailable"] and not result["canInstall"] and not result["installing"]
    assert "Intel Mac" in result["message"]


def test_download_installs_only_into_private_interpreter(setup, monkeypatch):
    (managed, _), _ = setup
    base = Path("read-only-install") / "python"
    worker = models._venv_python(models._setup_path(managed.parent / "runtime-v1"))
    calls = []
    def run(command, *, env, timeout, log):
        calls.append(command)
        assert "PYTHONPATH" not in env and "VIRTUAL_ENV" not in env
        print("test diagnostics", file=log)
        if "-m" in command and "venv" in command:
            worker.parent.mkdir(parents=True)
            worker.touch()
        else:
            assert Path(env["PATH"].split(os.pathsep)[0]).samefile(worker.parent)
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setenv("VIRTUAL_ENV", "/other-environment")
    monkeypatch.setenv("PYTHONPATH", "/app/base-packages")
    monkeypatch.setattr(models, "_run", run)
    monkeypatch.setattr(models, "_base", lambda: base)
    monkeypatch.setattr(models, "_usable", lru_cache()(lambda exe, stamp: exe.samefile(worker)))
    models._install_runtime()
    assert calls[0] == [base, "-I", "-B", "-m", "venv", str(worker.parents[1])]
    assert all(command[0].samefile(worker) and "install" in command for command in calls[1:])
    assert {"demucs==4.1.0", "stable-ts==2.19.1", "faster-whisper==1.2.1"} <= set(calls[-1])
    assert (managed.parent / "setup.log").read_text(encoding="utf-8").count("test diagnostics") == 3


def test_failed_setup_replaces_its_log_and_preserves_the_underlying_error(setup, monkeypatch):
    (managed, _), _ = setup
    managed.parent.mkdir(parents=True)
    log_file = managed.parent / "setup.log"
    log_file.write_text("previous attempt", encoding="utf-8")

    def fail(command, *, env, timeout, log):
        print("example package error", file=log)
        return subprocess.CompletedProcess(command, 19)

    monkeypatch.setattr(models, "_run", fail)
    with pytest.raises(RuntimeError, match="timing folder") as exc:
        models._install_runtime()
    saved = log_file.read_text(encoding="utf-8")
    assert "previous attempt" not in saved and "example package error" in saved and "Exit 19" in saved
    assert "example package error" not in str(exc.value)


@pytest.mark.skipif(os.name != "nt", reason="Windows' traditional path limit")
def test_can_write_deep_wheel_members_without_changing_windows_settings(tmp_path):
    root = models._setup_path(tmp_path / "runtime-v1")
    assert str(root).startswith("\\\\?\\") and models._setup_path(root) == root
    member = root / "Lib" / "site-packages" / ("package-" + "a" * 80) / ("headers-" + "b" * 80) / "model.h"
    assert len(str(member)) > 260
    member.parent.mkdir(parents=True)
    member.write_bytes(b"header")
    assert member.read_bytes() == b"header"
