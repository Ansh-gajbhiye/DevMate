"""SQLite growth profile (stdlib sqlite3).

Persists every review's findings and maintains per-category counters
that feed back into later review prompts and exercise generation.
Single file DB, default ~/.devmate/devmate.db (override DEVMATE_DB).
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS commits(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  repo TEXT NOT NULL,
  hash TEXT NOT NULL DEFAULT '',
  message TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS findings(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  commit_id INTEGER NOT NULL REFERENCES commits(id),
  category TEXT NOT NULL,
  severity TEXT NOT NULL,
  file TEXT NOT NULL,
  line INTEGER NOT NULL,
  note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS profile_counters(
  category TEXT PRIMARY KEY,
  count INTEGER NOT NULL DEFAULT 0,
  last_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS exercises(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  category TEXT NOT NULL,
  prompt TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL
);
"""


def default_db_path() -> str:
    if "DEVMATE_DB" in os.environ:
        return os.environ["DEVMATE_DB"]
    base = os.path.join(os.path.expanduser("~"), ".devmate")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "devmate.db")


def connect(path: str | None = None) -> sqlite3.Connection:
    db = sqlite3.connect(path or default_db_path())
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    init_db(db)
    return db


def init_db(db: sqlite3.Connection) -> None:
    db.executescript(SCHEMA)
    db.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_review(
    db: sqlite3.Connection,
    repo: str,
    findings,
    commit_hash: str = "",
    message: str = "",
) -> int:
    """Append one review. Returns commits.id."""
    cur = db.execute(
        "INSERT INTO commits(repo, hash, message, created_at) VALUES(?,?,?,?)",
        (repo, commit_hash, message, _now()),
    )
    cid = cur.lastrowid
    for f in findings:
        cat = f.category if hasattr(f, "category") else f["category"]
        sev = f.severity if hasattr(f, "severity") else f["severity"]
        path = f.file if hasattr(f, "file") else f["file"]
        line = f.line if hasattr(f, "line") else f["line"]
        note = (f.issue if hasattr(f, "issue") else f.get("issue", ""))
        db.execute(
            "INSERT INTO findings(commit_id, category, severity, file, line, note)"
            " VALUES(?,?,?,?,?,?)",
            (cid, cat, sev, path, line, note),
        )
        db.execute(
            "INSERT INTO profile_counters(category, count, last_seen)"
            " VALUES(?,1,?)"
            " ON CONFLICT(category) DO UPDATE SET"
            " count=count+1, last_seen=excluded.last_seen",
            (cat, _now()),
        )
    db.commit()
    return int(cid)


def top_weaknesses(db: sqlite3.Connection, limit: int = 3) -> list[tuple[str, int, str]]:
    rows = db.execute(
        "SELECT category, count, last_seen FROM profile_counters"
        " ORDER BY count DESC, last_seen DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [(r["category"], r["count"], r["last_seen"]) for r in rows]


def profile_summary(db: sqlite3.Connection, limit: int = 5) -> str:
    top = top_weaknesses(db, limit)
    if not top:
        return "No history yet."
    return "; ".join(f"{c} x{n}" for c, n, _ in top)
