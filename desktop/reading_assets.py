"""Add verified staged reading assets and the Windows language supplement to a package."""
from fetch_reading_models import MODELS, TARGET as READING_CACHE


def include_reading_assets(out, base):
    for key, _, _, names in MODELS:
        for name in names.split():
            out.write(READING_CACHE / key / name, f"{base}models/{key}/{name}")
    for notice in sorted(READING_CACHE.glob("*.txt")):
        out.write(notice, base + "models/" + notice.name)


def include_windows_language_packages(out, base, *extra_folders):
    supplement = READING_CACHE.parent.parent / "language-packages"
    if not (supplement / "transformers").is_dir() or not (supplement / "phonikud_onnx").is_dir():
        raise FileNotFoundError("Stage the Windows language packages in .build/language-packages.")
    emitted = set()
    for folder in (*extra_folders, supplement):
        for path in sorted(folder.rglob("*")):
            relative = path.relative_to(folder)
            if (
                "__pycache__" in relative.parts
                or relative.parts[:2] == ("pkg_resources", "tests")
                or relative.parts[0] in {"bin", "Scripts", "pip"}
                or relative.parts[0].startswith("pip-")
                or relative.parts[:2] in {("torch", "include"), ("torch", "share")}
                or path.suffix in {".lib", ".pth", ".pyc", ".whl"}
                or not path.is_file()
                or path.is_symlink()
            ):
                continue
            name = base + "processing-packages/" + relative.as_posix()
            if name in emitted:
                raise ValueError(f"Conflicting processing package file: {relative}")
            emitted.add(name)
            out.write(path, name)
