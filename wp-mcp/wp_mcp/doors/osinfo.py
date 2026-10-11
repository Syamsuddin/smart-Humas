"""Informasi OS untuk diagnosis ringan: disk, layanan, potongan log error (IP dimasker)."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b|\b(?:[0-9a-f]{1,4}:){3,7}[0-9a-f]{1,4}\b", re.I)


class OSInfo:
    def __init__(self, wp_path: str, error_logs: list[str] | None = None):
        self.wp_path = wp_path
        self.error_logs = error_logs or ["/var/log/nginx/error.log"]

    def disk(self) -> dict[str, Any]:
        try:
            u = shutil.disk_usage(self.wp_path)
        except OSError:
            return {}
        return {"total_gb": round(u.total / 1e9, 1), "free_gb": round(u.free / 1e9, 1),
                "used_pct": round(100 * u.used / u.total, 1)}

    def service_active(self, name: str) -> str | None:
        if not shutil.which("systemctl"):
            return None
        try:
            return subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            return None

    def error_tail(self, lines: int = 40) -> list[str]:
        out: list[str] = []
        for p in self.error_logs:
            path = Path(p)
            if not path.exists():
                continue
            try:
                tail = path.read_text(errors="replace").splitlines()[-lines:]
            except OSError:
                continue
            out += [_IP.sub("[IP]", x)[:400] for x in tail]
        return out[-lines:]
