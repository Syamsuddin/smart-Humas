"""Log audit append-only: satu baris JSON per panggilan tool.

Isi konten dipotong 200 karakter dan data pribadi dimasker. Rahasia tidak pernah ditulis.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .pii import PIIScanner

_CONTENT_KEYS = {"content", "content_markdown", "excerpt", "body", "instruction", "note",
                 "reviewer_note", "text", "data_base64", "markdown"}
_SECRET_HINTS = ("password", "token", "secret", "otp")


def _clip(value: Any, scanner: PIIScanner | None, limit: int = 200) -> Any:
    if isinstance(value, str):
        v = scanner.mask(value) if scanner else value
        return v if len(v) <= limit else v[:limit] + f"…(+{len(v) - limit})"
    return value


def sanitize_args(args: dict[str, Any], scanner: PIIScanner | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (args or {}).items():
        if any(h in k.lower() for h in _SECRET_HINTS):
            out[k] = "***"
        elif k in _CONTENT_KEYS:
            out[k] = _clip(v, scanner)
        elif isinstance(v, dict):
            out[k] = sanitize_args(v, scanner)
        elif isinstance(v, (list, tuple)):
            out[k] = [sanitize_args(x, scanner) if isinstance(x, dict) else _clip(x, scanner, 300) for x in v]
        elif isinstance(v, str):
            out[k] = _clip(v, scanner, 300)
        else:
            out[k] = v
    return out


class AuditLog:
    def __init__(self, log_dir: str | Path, scanner: PIIScanner | None = None):
        self.dir = Path(log_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "audit.jsonl"
        self.scanner = scanner
        self._lock = threading.Lock()
        self._seq = 0

    def new_id(self) -> str:
        with self._lock:
            self._seq += 1
            seq = self._seq
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return f"{stamp}-{os.getpid() % 100000:05d}-{seq:05d}"

    def write(self, entry: dict[str, Any]) -> None:
        entry = dict(entry)
        entry.setdefault("time", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        if "parameters" in entry:
            entry["parameters"] = sanitize_args(entry["parameters"], self.scanner)
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with self._lock:
            # O_APPEND menjamin baris utuh walau beberapa proses menulis bersamaan.
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o640)
            try:
                os.write(fd, (line + "\n").encode("utf-8"))
            finally:
                os.close(fd)

    def tail(self, n: int = 50) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()[-n:]
        return [json.loads(x) for x in lines if x.strip()]


def now() -> float:
    return time.time()
