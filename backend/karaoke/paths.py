"""Project folders. Everything is relative to the repo root (the folder holding CLAUDE.md)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INBOX = ROOT / "inbox"
SONGS = ROOT / "songs"
DATA = ROOT / "data"
FRONTEND_DIST = ROOT / "frontend" / "dist"
DB = DATA / "karaoke.db"
YT_COOKIES = DATA / "youtube-cookies.txt"  # optional sign-in cookies for downloads (gitignored)
