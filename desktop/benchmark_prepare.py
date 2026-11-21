"""Measure one real Prepare song job with the installed studio and a cleared audio clip."""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time


def run(studio, audio, language, start, end):
    import psutil
    studio = studio.resolve()
    sys.path.insert(0, str(studio))
    from launch import configure
    with tempfile.TemporaryDirectory(prefix="maagal-benchmark-") as temp:
        root = Path(temp)
        os.environ["KARAOKE_HOME"] = str(root / "listener")
        original_cwd = Path.cwd()
        try:
            configure()
            from karaoke import desktop_models, songfile
            env = os.environ.copy()
            env.update(desktop_models.worker_env(language))
            python = desktop_models.python_for(language)
            request = dict(slug="sample", audio=str(audio), language=language, title="Benchmark",
                           artist="", lyrics="", bilingual=False, start=start, end=end)
            (root / "request.json").write_text(json.dumps(request), "utf8")
            (root / "ready").touch()
            clock = time.perf_counter()
            peak = 0
            with subprocess.Popen([str(python), "-m", "karaoke.prepare", str(root)], env=env) as process:
                parent = psutil.Process(process.pid)
                while process.poll() is None:
                    try:
                        rss = sum(p.memory_info().rss for p in [parent, *parent.children(recursive=True)])
                        peak = max(rss, peak)
                    except psutil.NoSuchProcess:
                        pass
                    time.sleep(0.25)
                if process.returncode:
                    raise RuntimeError((root / "progress").read_text("utf8"))
            elapsed = time.perf_counter() - clock
            song = songfile.load(root / "song")
            fallback = [any(set(w["flags"]) & {"low-confidence", "timing-adjusted"} for w in line["words"])
                        for line in song["lines"]]
            return dict(platform=platform.platform(), cpu=platform.processor(), ramBytes=psutil.virtual_memory().total,
                        runtimeSeconds=round(elapsed, 2), sampledPeakTreeRSSBytes=peak,
                        durationMs=song["song"]["durationMs"], totalLines=len(fallback), fallbackLines=sum(fallback),
                        highlightedWords=sum(len(line["words"]) for line, use_line in zip(song["lines"], fallback)
                                             if not use_line), totalWords=sum(len(line["words"]) for line in song["lines"]))
        finally:
            os.chdir(original_cwd)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("studio", type=Path, help="Installed Studio resource directory")
    parser.add_argument("audio", type=Path)
    parser.add_argument("--language", choices=("he", "es"), default="he")
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--end", type=float, default=0)
    args = parser.parse_args()
    print(json.dumps(run(args.studio, args.audio.resolve(), args.language, args.start, args.end), indent=2))
