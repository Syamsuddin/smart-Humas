"""Tool operasional situs: status menyeluruh dan pembersihan cache (adaptor otomatis)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import __version__
from ..adapters import cache as cache_adapter
from ..adapters import security
from ..errors import WPMCPError
from ..policy import ToolContext, tool


def _theme_kind(ctx: ToolContext) -> dict[str, Any]:
    try:
        name = ctx.cli.run(["theme", "list", "--status=active", "--field=name"], max_level="0").stdout.strip().splitlines()[0]
    except (WPMCPError, IndexError):
        return {"active": None, "block_theme": None}
    tdir = Path(ctx.cfg.get("site.wp_path")) / "wp-content" / "themes" / name
    block = (tdir / "templates" / "index.html").exists() or (tdir / "block-templates" / "index.html").exists()
    return {"active": name, "block_theme": block,
            "theme_as_code": "tersedia" if block else "nonaktif: tema klasik (fitur konten tetap penuh)"}


@tool("site_status", level="0", group="site")
def site_status(ctx: ToolContext) -> dict:
    """Pemeriksaan kesehatan: REST dan hak akun editor-ai, plugin bridge, plugin keamanan dan cache (adaptor),
    versi core, jenis tema (blok/klasik), disk, layanan, dan kelengkapan Direktori. Jalankan setelah instalasi."""
    checks: list[dict[str, Any]] = []
    report: dict[str, Any] = {"wp_mcp_version": __version__, "site": ctx.cfg.get("site.url")}
    active: list[str] = []
    if ctx.cli is not None:
        try:
            report["core_version"] = ctx.cli.run(["core", "version"], max_level="0").stdout.strip()
            active = ctx.cli.active_plugins()
            report["cache"] = cache_adapter.detect(ctx.cli)
            report["theme"] = _theme_kind(ctx)
            checks.append({"check": "wp_cli", "ok": True})
        except WPMCPError as exc:
            checks.append({"check": "wp_cli", "ok": False, "error": exc.message})
    sec = security.probe(ctx.wp, active)
    report["rest"] = sec
    checks.append({"check": "rest_editor_ai", "ok": sec["rest_ok"], "hints": sec.get("hints")})
    try:
        ping = ctx.wp.get("/wpmcp/v1/ping").data
        report["bridge"] = ping
        checks.append({"check": "bridge_plugin", "ok": True})
    except WPMCPError as exc:
        checks.append({"check": "bridge_plugin", "ok": False, "error": exc.message,
                       "hint": "Aktifkan plugin wp-mcp-bridge di wp-admin → Plugins."})
    if ctx.services.osinfo is not None:
        report["disk"] = ctx.services.osinfo.disk()
        report["services"] = {s: ctx.services.osinfo.service_active(s) for s in ("nginx", "php8.3-fpm", "mysql")}
    from .directory import directory_status
    d = directory_status(ctx)
    report["directory"] = {"status": d["status"], "missing": d["missing"][:10]}
    checks.append({"check": "directory", "ok": d["status"] == "lengkap-wajib",
                   "hint": None if d["status"] == "lengkap-wajib" else "Jalankan skill /siapkan-direktori."})
    checks.append({"check": "telegram", "ok": bool(ctx.services.notifier.enabled),
                   "hint": None if ctx.services.notifier.enabled else "Notifikasi pimpinan & OTP level 3 belum aktif."})
    report["db_readonly"] = ctx.db is not None
    report["checks"] = checks
    report["healthy"] = all(c["ok"] for c in checks if c["check"] in ("rest_editor_ai", "bridge_plugin"))
    return report


def _describe_flush(ctx: ToolContext, args: dict) -> dict:
    return {"summary": "Bersihkan cache situs (object cache, transient, dan plugin cache yang terdeteksi)",
            "impact": ["halaman dibangun ulang saat dikunjungi; situs sedikit lebih lambat beberapa menit"]}


@tool("flush_cache", level="2b", describe_pending=_describe_flush, group="site")
def flush_cache(ctx: ToolContext) -> dict:
    """Bersihkan cache situs memakai adaptor plugin yang terdeteksi; jalur generik bila adaptor belum ada.
    (Penerbitan lewat approve_and_publish sudah membersihkan cache otomatis.)"""
    return cache_adapter.purge_all(ctx.cli)
