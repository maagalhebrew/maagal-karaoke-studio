"""Project folders. The default is this clone (the folder holding CLAUDE.md).

Set KARAOKE_HOME only when the writable library (inbox, songs, the database) should live
somewhere else. Set KARAOKE_RESOURCES only when the program files live apart from that library.
Neither variable is required. This app does not choose Documents, Desktop, or any other synced folder.
"""
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
