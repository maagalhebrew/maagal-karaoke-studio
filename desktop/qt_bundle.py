"""Copy the Qt Widgets and Multimedia modules, platform plugins and their linked libraries."""

from contextlib import ExitStack
from pathlib import PurePosixPath
import posixpath
import re
import struct
import zipfile

QT_ROOTS = {"QtCore", "QtGui", "QtWidgets", "QtNetwork", "QtMultimedia"}
KEEP_PLUGINS = {
    "platforms": {"qwindows", "qcocoa", "qoffscreen"},
    "multimedia": {"windowsmediaplugin", "darwinmediaplugin", "ffmpegmediaplugin"},
    "imageformats": {"qwebp", "qjpeg", "qico"},
    "styles": {"qmacstyle", "qmodernwindowsstyle"},
}


def mac_headers(data):
    if data[:4] == bytes.fromhex("cafebabe"):
        n = struct.unpack_from(">I", data, 4)[0]
        for i in range(n):
            _, _, start, size, _ = struct.unpack_from(">IIIII", data, 8 + 20 * i)
            yield from mac_headers(data[start : start + size])
        return
    if data[:4] != bytes.fromhex("cffaedfe"):
        return
    cpu = struct.unpack_from("<I", data, 4)[0]
    count = struct.unpack_from("<I", data, 16)[0]
    off, minimum, deps = 32, 0, []
    for _ in range(count):
        cmd, length = struct.unpack_from("<II", data, off)
        if cmd == 0x32:
            minimum = struct.unpack_from("<I", data, off + 12)[0]
        elif cmd == 0x24:
            minimum = struct.unpack_from("<I", data, off + 8)[0]
        elif cmd in (0xC, 0x80000018, 0x8000001F, 0x80000023):
            at = struct.unpack_from("<I", data, off + 8)[0] + off
            deps.append(data[at : off + length].split(b"\0", 1)[0].decode())
        off += length
    yield cpu, minimum, deps


def linked_names(data):
    if data[:2] == b"MZ":
        import pefile

        pe = pefile.PE(data=data, fast_load=True)
        pe.parse_data_directories(
            [
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"],
            ]
        )
        return [
            v.dll.decode()
            for table in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT")
            for v in getattr(pe, table, [])
        ]
    return list({dep for _, _, deps in mac_headers(data) for dep in deps})


def initial(path):
    parts = PurePosixPath(path).parts
    leaf = parts[-1]
    if ".dist-info" in parts[0]:
        return True
    if parts[0] == "shiboken6":
        return len(parts) == 2 and (
            leaf.endswith((".py", ".so", ".dll", ".pyd", ".dylib")) and not leaf.endswith(".abi3.lib")
        )
    if parts[0] != "PySide6":
        return False
    if len(parts) == 2:
        return (
            leaf in {"__init__.py", "_config.py", "_git_pyside_version.py"}
            or leaf.split(".")[0] in QT_ROOTS
            and leaf.endswith((".pyd", ".so"))
            or leaf.startswith(("pyside6.abi3.", "libpyside6.abi3."))
            and leaf.endswith((".dll", ".dylib"))
            or leaf.lower().startswith(("vcruntime", "msvcp140", "concrt140"))
            and leaf.endswith(".dll")
        )
    if parts[1] == "support" and leaf.endswith(".py"):
        return True
    if "plugins" in parts:
        which = parts[-2]
        stem = leaf.split(".")[0].removeprefix("lib")
        return stem in KEEP_PLUGINS.get(which, set())
    return False


def include_qt(out, base, cache, target, write):
    folder = cache / "qt" / ("mac" if target.startswith("mac") else "win64")
    wheels = sorted(folder.glob("*.whl"))
    if len(wheels) != 3:
        raise ValueError(f"Run desktop/fetch_native.py first ({target})")
    with ExitStack() as stack:
        files = {}
        for wheel in wheels:
            opened = stack.enter_context(zipfile.ZipFile(wheel))
            for info in opened.infolist():
                if not info.is_dir():
                    files.setdefault(info.filename, (opened, info))
        names = {}
        for path in files:
            leaf = PurePosixPath(path).name.lower()
            names.setdefault(leaf, []).append(path)
        pending = [p for p in files if initial(p)]
        kept = set()
        while pending:
            path = pending.pop()
            if path in kept:
                continue
            kept.add(path)
            z, info = files[path]
            data = z.read(info)
            mode = (info.external_attr >> 16) or 0o644
            write(out, base + "packages/" + path, data, mode)
            for dep in linked_names(data):
                if dep.startswith(("/System/", "/usr/lib/")):
                    continue
                rel = dep.split("/", 1)[-1]
                leaf = dep.rsplit("/", 1)[-1].lower()
                choices = names.get(leaf, [])
                resolved = next((p for p in choices if p.endswith("/" + rel)), None)
                if not resolved and dep.startswith("@loader_path/"):
                    direct = posixpath.normpath(posixpath.join(posixpath.dirname(path), rel))
                    if direct in files:
                        resolved = direct
                if not resolved and choices:
                    resolved = choices[0]
                if not resolved:
                    if dep.startswith("@"):
                        raise ValueError(f"Unresolved Qt library {path}: {dep}")
                    continue  # Windows system, Python and API-set DLLs
                if resolved not in kept:
                    pending.append(resolved)
            if re.search(r"\.framework/Versions/[^/]+/[^/]+$", path):
                parent = path.split(".framework/")[0] + ".framework/"
                for possible in files:
                    if possible.startswith(parent) and "/Resources/" in possible and possible not in kept:
                        pending.append(possible)
        assert not any("webengine" in p.lower() for p in kept)
        print(target, len(kept), "Qt files", flush=True)
