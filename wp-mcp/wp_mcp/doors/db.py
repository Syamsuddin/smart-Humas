"""Koneksi MySQL baca-saja (user wpmcp_ro, hanya SELECT). Dipakai audit konten massal.

Opsional: bila PyMySQL tidak terpasang atau kredensial tidak diisi, tool yang butuh DB
melaporkan NOT_CONFIGURED dan tool lain tetap berjalan.
"""

from __future__ import annotations

import re
from typing import Any

from ..errors import InvalidInput, NotConfigured

_WRITE_SQL = re.compile(r"^\s*(insert|update|delete|replace|drop|alter|create|truncate|grant|set|lock|call)\b", re.I)


class WPDatabase:
    def __init__(self, host: str, name: str, user: str, password: str, prefix: str = "wp_", port: int = 3306):
        try:
            import pymysql  # noqa: F401
        except ImportError:  # pragma: no cover - tergantung lingkungan
            raise NotConfigured("PyMySQL belum terpasang (pip install 'wp-mcp[db]').") from None
        self.params = dict(host=host, database=name, user=user, password=password, port=port, charset="utf8mb4")
        self.prefix = prefix

    def table(self, name: str) -> str:
        if not re.fullmatch(r"[a-z_]+", name):
            raise InvalidInput("nama tabel tidak sah")
        return f"`{self.prefix}{name}`"

    def select(self, sql: str, params: tuple | list = (), limit: int = 5000) -> list[dict[str, Any]]:
        if _WRITE_SQL.match(sql) or ";" in sql.strip().rstrip(";"):
            raise InvalidInput("Pintu DB hanya menerima satu perintah SELECT.")
        import pymysql
        conn = pymysql.connect(**self.params, cursorclass=pymysql.cursors.DictCursor, read_timeout=30)
        try:
            with conn.cursor() as cur:
                cur.execute("SET SESSION TRANSACTION READ ONLY")
                cur.execute(sql, params)
                return list(cur.fetchmany(limit))
        finally:
            conn.close()


def build_database(cfg) -> WPDatabase | None:
    host = cfg.secret("WPMCP_DB_HOST")
    user = cfg.secret("WPMCP_DB_USER")
    if not (host and user):
        return None
    try:
        return WPDatabase(host, cfg.secret("WPMCP_DB_NAME", "wordpress"), user, cfg.secret("WPMCP_DB_PASSWORD", ""),
                          cfg.secret("WPMCP_DB_PREFIX", "wp_"), int(cfg.secret("WPMCP_DB_PORT", "3306")))
    except NotConfigured:
        return None
