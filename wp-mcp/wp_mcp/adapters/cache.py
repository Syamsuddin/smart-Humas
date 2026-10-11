"""Adaptor pembersih cache: pilih perintah purge sesuai plugin cache yang aktif."""

from __future__ import annotations

from typing import Any

from ..doors.cli import WPCli
from ..errors import WPMCPError

# slug plugin → perintah purge seluruh situs (harus ada di cli_whitelist.yaml)
CACHE_ADAPTERS: dict[str, list[str]] = {
    "litespeed-cache": ["litespeed-purge", "all"],
    "w3-total-cache": ["w3-total-cache", "flush", "all"],
    "wp-super-cache": ["super-cache", "flush"],
    "wp-fastest-cache": ["fastest-cache", "clear", "all"],
    "autoptimize": ["autoptimize", "clear"],
    "sg-cachepress": ["sg", "purge"],
    "breeze": ["breeze", "purge", "--cache=all"],
    "nginx-helper": ["nginx-helper", "purge-all"],
    "wp-optimize": ["wp-optimize", "cache", "purge"],
}

# plugin cache yang dikenal tetapi belum punya perintah WP-CLI yang andal
KNOWN_WITHOUT_CLI = {"wp-rocket", "cache-enabler", "hummingbird-performance", "comet-cache"}


def detect(cli: WPCli) -> dict[str, Any]:
    active = cli.active_plugins()
    adapters = [p for p in active if p in CACHE_ADAPTERS]
    unsupported = [p for p in active if p in KNOWN_WITHOUT_CLI]
    return {"active_plugins": active, "cache_adapters": adapters, "cache_plugins_without_adapter": unsupported}


def purge_all(cli: WPCli, detected: dict[str, Any] | None = None) -> dict[str, Any]:
    """Bersihkan cache situs. Selalu jalankan object cache flush; tambah purge plugin bila terdeteksi."""
    detected = detected or detect(cli)
    ran: list[str] = []
    failed: list[dict[str, str]] = []
    for args in [["cache", "flush"], ["transient", "delete", "--expired"]] + [CACHE_ADAPTERS[p] for p in detected["cache_adapters"]]:
        try:
            cli.run(args, max_level="2b")
            ran.append(" ".join(args))
        except WPMCPError as exc:
            failed.append({"command": " ".join(args), "error": exc.message})
    return {"ran": ran, "failed": failed, "generic_only": not detected["cache_adapters"],
            "unsupported_plugins": detected["cache_plugins_without_adapter"]}
