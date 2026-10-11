"""CLI wp-mcp.

  wp-mcp serve --actor <id>             jalankan server MCP lewat stdio (dipanggil launcher SSH)
  wp-mcp check                          pemeriksaan kesehatan (site_status) sebagai operator-ai
  wp-mcp call <tool> --actor <id> --args '{"..."}'   panggil satu tool (uji/otomasi)
  wp-mcp tools                          daftar tool, level, dan peran
  wp-mcp directory-import <berkas.md> --actor <id>
  wp-mcp audit-tail [-n 20]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="wp-mcp")
    ap.add_argument("--config-dir", default=None, help="bawaan /etc/wp-mcp atau $WPMCP_CONFIG_DIR")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve")
    s.add_argument("--actor", required=True)
    s.add_argument("--door", default="claude_code")

    sub.add_parser("check")
    c = sub.add_parser("call")
    c.add_argument("tool")
    c.add_argument("--actor", default="operator-ai")
    c.add_argument("--args", default="{}")
    sub.add_parser("tools")
    d = sub.add_parser("directory-import")
    d.add_argument("file")
    d.add_argument("--actor", required=True)
    d.add_argument("--replace", action="store_true")
    a = sub.add_parser("audit-tail")
    a.add_argument("-n", type=int, default=20)

    ns = ap.parse_args(argv)

    if ns.cmd == "tools":
        from . import tools  # noqa: F401
        from .policy import REGISTRY
        for spec in sorted(REGISTRY.values(), key=lambda x: (x.group, x.name)):
            print(f"{spec.group:12} {spec.name:26} level {spec.level:3} {', '.join(spec.allowed_roles)}")
        return 0

    from .app import build_dispatcher
    disp = build_dispatcher(ns.config_dir)

    if ns.cmd == "serve":
        from .server import build_server
        build_server(disp, ns.actor, ns.door).run()
        return 0
    if ns.cmd == "check":
        _print(disp.call("operator-ai", "site_status", {}, door="cli"))
        return 0
    if ns.cmd == "call":
        _print(disp.call(ns.actor, ns.tool, json.loads(ns.args), door="cli"))
        return 0
    if ns.cmd == "directory-import":
        text = Path(ns.file).read_text(encoding="utf-8")
        _print(disp.call(ns.actor, "directory_import", {"markdown": text, "replace": ns.replace}, door="cli"))
        return 0
    if ns.cmd == "audit-tail":
        _print(disp.s.audit.tail(ns.n))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
