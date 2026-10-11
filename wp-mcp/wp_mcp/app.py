"""Merakit layanan WP-MCP dari konfigurasi: penyimpanan, audit, pintu WordPress, notifikasi, dispatcher."""

from __future__ import annotations

from pathlib import Path

from . import tools  # noqa: F401  (mendaftarkan semua tool)
from .audit import AuditLog
from .config import Config, load_config
from .doors.cli import WPCli
from .doors.db import build_database
from .doors.osinfo import OSInfo
from .doors.rest import WPRest
from .notifier import build_notifier
from .pii import PIIScanner
from .policy import Dispatcher, Services
from .state import State


def build_services(cfg: Config, *, wp=None, cli=None, notifier=None, clock=None) -> Services:
    scanner = PIIScanner(cfg.pii_patterns)
    state = State(Path(cfg.state_dir) / "state.db")
    audit = AuditLog(cfg.log_dir, scanner)
    if wp is None:
        wp = WPRest(cfg.get("site.rest_base") or cfg.get("site.url"), cfg.secret("WPMCP_WP_USER"),
                    cfg.secret("WPMCP_WP_APP_PASSWORD"), rest_prefix=cfg.get("site.rest_prefix", "/wp-json"),
                    host_header=cfg.get("site.host_header"), verify_tls=bool(cfg.get("site.verify_tls", True)),
                    timeout=float(cfg.get("site.timeout", 30)),
                    bridge_key=cfg.secret("WPMCP_BRIDGE_KEY"))
    if cli is None:
        cli = WPCli(cfg.get("site.wp_path"), cfg.cli_whitelist, binary=cfg.get("site.wp_cli", "wp"),
                    sudo_user=cfg.get("site.wp_cli_sudo_user") or None)
    services = Services(cfg=cfg, state=state, audit=audit, scanner=scanner,
                        notifier=notifier or build_notifier(cfg), wp=wp, cli=cli, db=build_database(cfg),
                        osinfo=OSInfo(cfg.get("site.wp_path"), cfg.get("site.error_logs")))
    if clock is not None:
        services.clock = clock
    services.dispatcher = Dispatcher(services)
    return services


def build_dispatcher(config_dir: str | Path | None = None, **overrides) -> Dispatcher:
    return build_services(load_config(config_dir), **overrides).dispatcher
