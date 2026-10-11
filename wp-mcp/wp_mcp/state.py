"""Penyimpanan lokal WP-MCP (SQLite, satu berkas per situs).

Menyimpan hal yang tidak boleh atau tidak perlu tinggal di WordPress:
aksi tertunda, kunci idempotensi, hitungan tulis (rate limit), Memori Redaksi,
Direktori Resmi, dan delegasi. Tidak menyimpan rahasia.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_actions (
    id TEXT PRIMARY KEY,
    tool TEXT NOT NULL,
    level TEXT NOT NULL,
    actor TEXT NOT NULL,
    args_json TEXT NOT NULL,
    summary TEXT NOT NULL,
    impact_json TEXT NOT NULL DEFAULT '[]',
    content_hash TEXT,
    target_ref TEXT,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    otp_hash TEXT,
    otp_expires_at REAL,
    status TEXT NOT NULL DEFAULT 'pending',
    result_json TEXT,
    confirmed_by TEXT,
    confirmed_at REAL,
    door TEXT,
    oob INTEGER NOT NULL DEFAULT 0,
    otp_attempts INTEGER NOT NULL DEFAULT 0,
    channels_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS idempotency (
    key TEXT NOT NULL,
    actor TEXT NOT NULL,
    tool TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (key, actor, tool)
);
CREATE TABLE IF NOT EXISTS writes (
    actor TEXT NOT NULL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS writes_actor_ts ON writes(actor, ts);
CREATE TABLE IF NOT EXISTS memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    status TEXT NOT NULL,
    source TEXT NOT NULL,
    source_ref TEXT,
    trust TEXT NOT NULL DEFAULT 'D',
    hits INTEGER NOT NULL DEFAULT 1,
    proposed_by TEXT,
    confirmed_by TEXT,
    confirmed_at REAL,
    valid_until REAL,
    used_count INTEGER NOT NULL DEFAULT 0,
    last_used_at REAL,
    supersedes INTEGER,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS memory_kind_key ON memory(kind, key);
CREATE TABLE IF NOT EXISTS directory (
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    record_json TEXT NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0,
    source TEXT,
    updated_at REAL NOT NULL,
    updated_by TEXT,
    PRIMARY KEY (kind, key)
);
CREATE TABLE IF NOT EXISTS directory_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS directory_log (
    ts REAL NOT NULL,
    section TEXT NOT NULL,
    change TEXT NOT NULL,
    actor TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS delegations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_actor TEXT NOT NULL,
    to_actor TEXT NOT NULL,
    categories_json TEXT NOT NULL DEFAULT '[]',
    until REAL NOT NULL,
    note TEXT,
    created_at REAL NOT NULL,
    revoked_at REAL,
    revoked_by TEXT
);
"""


class State:
    """Pembungkus SQLite yang aman dipakai lintas thread (satu koneksi, dikunci)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            if str(path) != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)
            self._migrate()

    def _migrate(self) -> None:
        """Tambah kolom yang belum ada pada basis data versi lama (idempoten)."""
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(pending_actions)").fetchall()}
        for name, ddl in (("door", "TEXT"), ("oob", "INTEGER NOT NULL DEFAULT 0"),
                          ("otp_attempts", "INTEGER NOT NULL DEFAULT 0"),
                          ("channels_json", "TEXT NOT NULL DEFAULT '[]'")):
            if name not in cols:
                self._conn.execute(f"ALTER TABLE pending_actions ADD COLUMN {name} {ddl}")

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, tuple(params))

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, tuple(params)).fetchall()]

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    # --- rate limit -------------------------------------------------------
    def record_write(self, actor: str, now: float | None = None) -> None:
        now = now or time.time()
        self.execute("INSERT INTO writes(actor, ts) VALUES (?, ?)", (actor, now))
        self.execute("DELETE FROM writes WHERE ts < ?", (now - 3600,))

    def writes_since(self, actor: str, since: float) -> int:
        row = self.one("SELECT COUNT(*) AS n FROM writes WHERE actor=? AND ts>=?", (actor, since))
        return int(row["n"]) if row else 0

    # --- idempotensi ------------------------------------------------------
    def idem_get(self, key: str, actor: str, tool: str, ttl: float = 86400) -> dict | None:
        row = self.one(
            "SELECT result_json, created_at FROM idempotency WHERE key=? AND actor=? AND tool=?",
            (key, actor, tool),
        )
        if not row or time.time() - row["created_at"] > ttl:
            return None
        return json.loads(row["result_json"])

    def idem_put(self, key: str, actor: str, tool: str, result: dict) -> None:
        self.execute(
            "INSERT OR REPLACE INTO idempotency(key, actor, tool, result_json, created_at) VALUES (?,?,?,?,?)",
            (key, actor, tool, json.dumps(result, ensure_ascii=False, default=str), time.time()),
        )

    # --- metadata direktori ----------------------------------------------
    def meta_get(self, key: str, default: str | None = None) -> str | None:
        row = self.one("SELECT value FROM directory_meta WHERE key=?", (key,))
        return row["value"] if row else default

    def meta_set(self, key: str, value: str) -> None:
        self.execute("INSERT OR REPLACE INTO directory_meta(key, value) VALUES (?, ?)", (key, value))
