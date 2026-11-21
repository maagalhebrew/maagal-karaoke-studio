"""Open Maagal Karaoke Studio in a native Qt window. The only user data directory is the library."""

import contextlib
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "backend").exists() else HERE.parent


def library_path():
    if os.environ.get("KARAOKE_HOME"):
        return Path(os.environ["KARAOKE_HOME"]).expanduser().resolve()
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Karaoke IL"
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Karaoke IL"


def configure():
    home = library_path()
    for directory in (home / "songs", home / "inbox", home / "data"):
        directory.mkdir(parents=True, exist_ok=True)
    backend, packages = str(ROOT / "backend"), str(ROOT / "packages")
    sys.path[:0] = [str(HERE), backend, packages]
    os.environ.update(
        KARAOKE_HOME=str(home),
        KARAOKE_RESOURCES=str(ROOT),
        KARAOKE_DESKTOP="1",
        KARAOKE_RESOURCE_PYTHON=sys.executable,
        KARAOKE_PYTHON=sys.executable,
        PYTHONPATH=os.pathsep.join((backend, packages)),
        PYTHONNOUSERSITE="1",
        PATH=str(ROOT / "tools") + os.pathsep + os.environ.get("PATH", ""),
    )
    os.chdir(home)
    return home


@contextlib.contextmanager
def library_lock(home):
    # Same operating-system lock used by the preceding desktop edition.
    with (home / "desktop.lock").open("a+b") as lock:
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
        else:
            yield True


def main():
    home = configure()
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox
    from native.theme import assets, apply_theme
    from native.window import MainWindow

    app = QApplication([sys.argv[0]])
    app.setApplicationName("Karaoke IL")
    app.setOrganizationName("Maagal Hebrew")
    app.setApplicationDisplayName("Maagal Karaoke Studio")
    app.setWindowIcon(QIcon(str(assets / "app.png")))
    apply_theme(app)
    with library_lock(home) as acquired:
        if not acquired:
            QMessageBox.information(
                None,
                app.applicationDisplayName(),
                "Your library is already open. Switch to Maagal Karaoke Studio to continue.",
            )
            return 0
        window = MainWindow()
        window.show()
        return app.exec()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback

        home = library_path()
        home.mkdir(parents=True, exist_ok=True)
        log = home / "startup-error.txt"
        log.write_text(traceback.format_exc(), encoding="utf-8")
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None,
                "Maagal Karaoke Studio could not start. Reinstall the app or share the startup-error.txt file from your library folder.",
                "Maagal Karaoke Studio",
                16,
            )
        elif sys.platform == "darwin":
            import subprocess

            subprocess.run(
                [
                    "/usr/bin/osascript",
                    "-e",
                    'display alert "Maagal Karaoke Studio could not start." message "Open Library/Application Support/Karaoke IL/startup-error.txt for details."',
                ],
                check=False,
            )
        raise
