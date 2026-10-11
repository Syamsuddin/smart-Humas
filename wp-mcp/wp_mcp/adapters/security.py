"""Deteksi plugin keamanan dan uji apakah REST API bisa dipakai akun editor-ai.

WP-MCP tidak pernah mengubah pengaturan keamanan atau mematikan firewall;
ia hanya melaporkan langkah pengecualian untuk Admin.
"""

from __future__ import annotations

from typing import Any

from ..errors import WPRejected

SECURITY_HINTS: dict[str, str] = {
    "wordfence": "Wordfence → All Options → Brute Force Protection: pastikan 'Disable WordPress application passwords' TIDAK dicentang; "
                 "Firewall → Allowlisted IP: tambahkan 127.0.0.1.",
    "better-wp-security": "Solid Security → Settings → Advanced → WordPress Tweaks: REST API 'Default Access', jangan 'Restricted Access'.",
    "solid-security": "Solid Security → Settings → Advanced → WordPress Tweaks: REST API 'Default Access'.",
    "all-in-one-wp-security-and-firewall": "AIOS → Miscellaneous → WP REST API: jangan centang 'Disallow unauthorized REST requests', "
                                           "atau tambahkan pengecualian untuk route /wp/v2 dan /wpmcp/v1.",
    "sucuri-scanner": "Sucuri → Settings → Hardening: jangan blokir REST API; allowlist 127.0.0.1 di Sucuri WAF bila dipakai.",
    "disable-json-api": "Plugin Disable REST API: izinkan route /wp/v2/* dan /wpmcp/v1/* untuk peran Editor AI.",
    "disable-wp-rest-api": "Plugin ini mematikan REST untuk pengguna anonim saja; pastikan autentikasi application password diterima.",
    "limit-login-attempts-reloaded": "Tambahkan 127.0.0.1 ke allowlist agar kegagalan autentikasi lokal tidak mengunci akun.",
}


def probe(wp: Any, active_plugins: list[str]) -> dict[str, Any]:
    present = [p for p in active_plugins if p in SECURITY_HINTS]
    result: dict[str, Any] = {"security_plugins": present, "rest_ok": False, "as_user": None, "hints": []}
    try:
        me = wp.get("/wp/v2/users/me", context="edit").data
        result["rest_ok"] = True
        result["as_user"] = {"id": me.get("id"), "slug": me.get("slug"), "roles": me.get("roles")}
        caps = me.get("capabilities") or {}
        result["can_publish"] = bool(caps.get("publish_posts"))
        if me.get("roles") and "editor_ai" not in me.get("roles", []):
            result["hints"].append("Akun REST bukan berperan editor_ai. Gunakan akun khusus editor-ai, bukan Administrator.")
    except WPRejected as exc:
        result["error"] = exc.message
        result["http_status"] = exc.detail.get("http_status")
        result["hints"] = [SECURITY_HINTS[p] for p in present] or [
            "Periksa application password akun editor-ai dan pastikan REST API tidak diblokir firewall/WAF untuk 127.0.0.1."]
    return result
