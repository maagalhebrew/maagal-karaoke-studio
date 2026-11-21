"""Fetch the pinned Hebrew reading models into the desktop packaging cache."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from urllib.request import urlopen

TARGET = Path(__file__).resolve().parents[1] / ".build" / "desktop" / "models"
MODELS = [
    ("he-en", "Helsinki-NLP/opus-mt-tc-big-he-en", "134c5a850dcaa763eec85bd1f4eb25112fecedbb",
     "README.md config.json generation_config.json model.safetensors source.spm target.spm tokenizer_config.json vocab.json special_tokens_map.json"),
    ("pronunciation-tokenizer", "dicta-il/dictabert-large-char-menaked", "4dfc20b94565d7868e1c8c00bf039d38c071a062", "README.md tokenizer.json"),
    ("pronunciation", "Phonikud/phonikud-onnx", "b806189fe1fc0085b1012b7560ffb5e8ecfd72a2",
     "README.md phonikud-1.0.int8.onnx"),
]


def fetch():
    TARGET.mkdir(parents=True, exist_ok=True)
    (TARGET / "Reading model credits.txt").write_text(
        "Hebrew to English: Helsinki-NLP, OPUS-MT. https://huggingface.co/Helsinki-NLP/opus-mt-tc-big-he-en\n"
        "CC BY 4.0 https://creativecommons.org/licenses/by/4.0/\n"
        "Hebrew phonetic marks: Phonikud int8 ONNX (MIT). https://huggingface.co/Phonikud/phonikud-onnx\n"
        "Character tokenizer: Dicta, DictaBERT. https://huggingface.co/dicta-il/dictabert-large-char-menaked\n"
        "Grapheme-to-phoneme software: Phonikud. https://github.com/phonikud/phonikud\n"
        "Unmodified publisher assets. See the included version-specific model cards for attribution.\n", "utf8")
    for key, repo, revision, names in MODELS:
        with urlopen(f"https://huggingface.co/api/models/{repo}/tree/{revision}", timeout=60) as response:
            files = {item["path"]: item for item in json.load(response)}
        folder = TARGET / key
        folder.mkdir(parents=True, exist_ok=True)
        for name in names.split():
            data = files[name]
            large = data.get("lfs")
            checksum = large["oid"] if large else data["oid"]
            dest = folder / name

            def matches(path):
                if not path.exists() or path.stat().st_size != data["size"]:
                    return False
                digest = hashlib.sha256() if large else hashlib.sha1(f"blob {data['size']}".encode() + bytes(1))
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                return digest.hexdigest() == checksum

            if matches(dest):
                continue
            with tempfile.NamedTemporaryFile(dir=folder, delete=False) as stream:
                pending = Path(stream.name)
            try:
                with urlopen(f"https://huggingface.co/{repo}/resolve/{revision}/{name}", timeout=120) as response, pending.open("wb") as out:
                    shutil.copyfileobj(response, out)
                if not matches(pending):
                    raise ValueError(f"Checksum mismatch for {repo}/{name}")
                os.replace(pending, dest)
            finally:
                pending.unlink(missing_ok=True)
            print(key, name, data["size"], flush=True)


if __name__ == "__main__":
    fetch()
