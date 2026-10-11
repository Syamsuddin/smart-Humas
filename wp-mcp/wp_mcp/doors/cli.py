"""Pembungkus WP-CLI dengan whitelist. Tanpa shell, argumen selalu berupa list."""

from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from typing import Any

from ..errors import CommandNotAllowed, WPRejected


@dataclass
class CliResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str

    def json(self) -> Any:
        return json.loads(self.stdout or "null")


class WPCli:
    def __init__(self, wp_path: str, whitelist: dict[str, Any], *, binary: str = "wp",
                 sudo_user: str | None = None, timeout: float = 300.0):
        self.wp_path = wp_path
        self.binary = binary
        self.sudo_user = sudo_user
        self.timeout = timeout
        self.rules = [(list(map(str, c["match"])), str(c.get("level", "0"))) for c in whitelist.get("commands", [])]
        self.forbidden = [str(a) for a in whitelist.get("forbidden_args", [])]

    def level_of(self, args: list[str]) -> str:
        """Level risiko perintah; CommandNotAllowed bila tidak ada di whitelist."""
        for a in args:
            for f in self.forbidden:
                if a == f or (f.startswith("--") and a.startswith(f + "=")):
                    raise CommandNotAllowed(f"Argumen '{a}' selalu ditolak oleh WP-MCP.")
        best: tuple[int, str] | None = None
        for pattern, level in self.rules:
            if args[: len(pattern)] == pattern and (best is None or len(pattern) > best[0]):
                best = (len(pattern), level)
        if best is None:
            raise CommandNotAllowed(
                f"Perintah 'wp {shlex.join(args)}' tidak ada di cli_whitelist.yaml.",
                detail={"hint": "Tambahkan ke /etc/wp-mcp/cli_whitelist.yaml bila memang dibutuhkan, dengan level yang tepat."})
        return best[1]

    def command(self, args: list[str]) -> list[str]:
        base = [self.binary, f"--path={self.wp_path}", "--no-color"]
        if self.sudo_user:
            base = ["sudo", "-n", "-u", self.sudo_user] + base
        return base + list(args)

    def run(self, args: list[str], *, max_level: str = "3", check: bool = True) -> CliResult:
        level = self.level_of(args)
        order = ["0", "1", "2a", "2b", "3"]
        if order.index(level) > order.index(max_level):
            raise CommandNotAllowed(f"Perintah level {level} tidak boleh dijalankan dari konteks level {max_level}.")
        try:
            proc = subprocess.run(self.command(args), capture_output=True, text=True, timeout=self.timeout)
        except FileNotFoundError:
            raise WPRejected(f"WP-CLI tidak ditemukan ({self.binary}).") from None
        except subprocess.TimeoutExpired:
            raise WPRejected(f"WP-CLI melewati batas waktu {self.timeout} detik: wp {shlex.join(args)}") from None
        res = CliResult(args, proc.returncode, proc.stdout, proc.stderr)
        if check and proc.returncode != 0:
            raise WPRejected(f"WP-CLI gagal: wp {shlex.join(args)}",
                             detail={"returncode": proc.returncode, "stderr": proc.stderr[-800:]})
        return res

    def active_plugins(self) -> list[str]:
        res = self.run(["plugin", "list", "--status=active", "--field=name"], max_level="0", check=False)
        return [x.strip() for x in res.stdout.splitlines() if x.strip()] if res.returncode == 0 else []
