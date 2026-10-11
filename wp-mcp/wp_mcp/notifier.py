"""Pemberitahuan keluar: pesan Telegram ke aktor (antrean pimpinan, draft dikembalikan, kode OTP).

Hanya memakai Bot API sendMessage lewat urllib; tidak menyimpan riwayat percakapan.
Isi berita tidak pernah dikirim, hanya ringkasan dan ID.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from typing import Protocol

from .config import Actor, Config

log = logging.getLogger("wp_mcp.notifier")


class Notifier(Protocol):
    def send(self, actor: Actor, text: str) -> bool: ...

    @property
    def enabled(self) -> bool: ...


class NullNotifier:
    enabled = False

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, actor: Actor, text: str) -> bool:
        self.sent.append((actor.id, text))
        return False


class TelegramNotifier:
    def __init__(self, token: str, timeout: float = 10.0):
        self.token = token
        self.timeout = timeout
        self.enabled = True

    def send(self, actor: Actor, text: str) -> bool:
        chat_id = actor.telegram_chat_id or actor.telegram_user_id
        if not chat_id:
            return False
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        body = urllib.parse.urlencode({"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=self.timeout) as resp:
                return bool(json.loads(resp.read().decode()).get("ok"))
        except Exception as exc:  # jaringan gagal tidak boleh menggagalkan tool
            log.warning("Telegram gagal mengirim ke %s: %s", actor.id, exc)
            return False


def build_notifier(cfg: Config) -> Notifier:
    token = cfg.secret("WPMCP_TELEGRAM_TOKEN")
    if cfg.get("notify.telegram.enabled") and token:
        return TelegramNotifier(token)
    return NullNotifier()
