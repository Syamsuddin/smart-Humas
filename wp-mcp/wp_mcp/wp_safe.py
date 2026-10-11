"""Pembungkus WP-CLI milik root: satu-satunya perintah yang boleh dijalankan wpmcp lewat sudo.

  sudoers:  wpmcp ALL=(www-data) NOPASSWD: /opt/wp-mcp/bin/wp-safe

Whitelist ditegakkan DI SINI (di balik batas sudo), bukan hanya di proses WP-MCP, sehingga proses
wpmcp yang disusupi pun tidak bisa menjalankan `wp eval`, `wp db query`, `wp user create`, dll.
Path WordPress dan binari wp dibaca dari /opt/wp-mcp/wp-safe.json (milik root), bukan dari argumen.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml

from .doors.cli import WPCli
from .errors import CommandNotAllowed

CONF = Path(os.environ.get("WPSAFE_CONF_FOR_TESTS", "/opt/wp-mcp/wp-safe.json"))
GLOBAL_FORBIDDEN = ("--path", "--ssh", "--http", "--url", "--user", "--require", "--exec", "--context")


def build_argv(argv: list[str], conf: dict) -> list[str]:
    args = [a for a in argv if a != "--no-color" and not a.startswith("--path=")]
    for a in args:
        if a.split("=", 1)[0] in GLOBAL_FORBIDDEN:
            raise CommandNotAllowed(f"Argumen global '{a}' tidak diizinkan.")
    whitelist = yaml.safe_load(Path(conf["whitelist"]).read_text(encoding="utf-8"))
    WPCli(conf["wp_path"], whitelist).level_of(args)  # melempar CommandNotAllowed bila tidak sah
    return [conf["wp_bin"], f"--path={conf['wp_path']}", "--no-color", *args]


def main() -> None:
    try:
        conf = json.loads(CONF.read_text(encoding="utf-8"))
        argv = build_argv(sys.argv[1:], conf)
    except CommandNotAllowed as exc:
        print(f"wp-safe: {exc.message}", file=sys.stderr)
        sys.exit(126)
    except (OSError, ValueError, KeyError) as exc:
        print(f"wp-safe: konfigurasi tidak terbaca: {exc}", file=sys.stderr)
        sys.exit(125)
    # Lingkungan bersih: tanpa wp-cli.yml dari folder kerja, tanpa paket WP-CLI dari HOME, tanpa variabel warisan.
    os.chdir("/")
    env = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "HOME": "/nonexistent",
           "WP_CLI_CONFIG_PATH": "/dev/null", "WP_CLI_PACKAGES_DIR": "/nonexistent",
           "WP_CLI_DISABLE_AUTO_CHECK_UPDATE": "1", "LANG": "C.UTF-8"}
    os.execve(argv[0], argv, env)


if __name__ == "__main__":
    main()
