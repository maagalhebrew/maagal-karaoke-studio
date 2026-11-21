"""Keep the desktop installation separate from the listener's writable library."""
import os
from pathlib import Path

ROOT = Path(os.environ.get("KARAOKE_RESOURCES") or Path(__file__).resolve().parents[2])
HOME = Path(os.environ.get("KARAOKE_HOME") or ROOT)
INBOX = HOME / "inbox"
SONGS = HOME / "songs"
DATA = HOME / "data"
FRONTEND_DIST = ROOT / "frontend" / "dist"
DB = DATA / "karaoke.db"
YT_COOKIES = DATA / "youtube-cookies.txt"  # optional sign-in cookies for downloads (gitignored)
