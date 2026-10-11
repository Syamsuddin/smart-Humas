"""Memuat konfigurasi WP-MCP dari direktori konfigurasi (bawaan /etc/wp-mcp).

Berkas:
- config.yaml        pengaturan situs, media, privasi, batas
- actors.yaml        tiga peran: operator-ai, admin-web, pimpinan
- secrets.env        rahasia (mode 600), tidak pernah masuk log atau respons tool
- cli_whitelist.yaml (opsional) menimpa daftar perintah WP-CLI bawaan
- pii_patterns.yaml  (opsional) menimpa pola data pribadi bawaan
- gaya-rumah.md      (opsional) menimpa pedoman gaya redaksi bawaan
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from .errors import NotConfigured

ROLES = ("operator-ai", "admin-web", "pimpinan")

DEFAULTS: dict[str, Any] = {
    "site": {
        "url": "",
        "wp_path": "/var/www/html",
        "wp_cli": "wp",
        "rest_base": "",
        "rest_prefix": "/wp-json",
        "host_header": "",
        "verify_tls": True,
        "timeout": 30,
        "wp_cli_sudo_user": "",
        "error_logs": ["/var/log/nginx/error.log"],
    },
    "state_dir": "/var/lib/wp-mcp",
    "log_dir": "/var/log/wp-mcp",
    "media": {
        "featured": {"width": 1200, "height": 675, "quality": 82, "max_kb": 300},
        "inline": {"width": 1024, "quality": 80, "max_kb": 250},
        "gallery": {"width": 800, "quality": 78, "max_kb": 200},
        "social": {"width": 1080, "height": 1080, "quality": 85, "max_kb": 400},
    },
    "privacy": {"pii_scan": True, "mask_commenter": True, "ocr_media": True},
    "limits": {
        "writes_per_10min": 30,
        "pending_action_minutes": 15,
        "otp_minutes": 5,
        "leader_reminder_hours": 24,
        "delegation_max_days": 14,
        "content_max_kb": 200,
        "proposal_ttl_days": 14,
    },
    "workflow": {"require_review_before_publish": True},
    "reply": {"signature": "Admin Website"},
    "notify": {"telegram": {"enabled": False}},
    "otp": {"channel": "telegram"},
    "approvals": {"wp_admin": True},
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        values[key.strip()] = val
    return values


@dataclass
class Actor:
    id: str
    role: str
    name: str = ""
    technical_admin: bool = False
    telegram_user_id: int | None = None
    telegram_chat_id: int | None = None
    wp_user: str | None = None  # login WordPress manusia ini, untuk persetujuan di wp-admin

    @property
    def label(self) -> str:
        return self.name or self.id


@dataclass
class Config:
    data: dict[str, Any]
    config_dir: Path
    secrets: dict[str, str] = field(default_factory=dict)
    actors: dict[str, Actor] = field(default_factory=dict)
    cli_whitelist: dict[str, Any] = field(default_factory=dict)
    pii_patterns: dict[str, Any] = field(default_factory=dict)
    style_guide: str = ""

    # akses ringkas
    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self.data
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def secret(self, key: str, default: str | None = None) -> str | None:
        return os.environ.get(key) or self.secrets.get(key) or default

    @property
    def state_dir(self) -> Path:
        return Path(self.data["state_dir"])

    @property
    def log_dir(self) -> Path:
        return Path(self.data["log_dir"])

    def actor(self, actor_id: str) -> Actor:
        if actor_id not in self.actors:
            raise NotConfigured(
                f"Aktor '{actor_id}' tidak terdaftar di actors.yaml.",
                detail={"known_actors": sorted(self.actors)},
            )
        return self.actors[actor_id]

    def actors_with_role(self, role: str) -> list[Actor]:
        return [a for a in self.actors.values() if a.role == role]


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise NotConfigured(f"{path} harus berisi objek YAML.")
    return data


def _packaged_text(name: str) -> str:
    return resources.files("wp_mcp").joinpath("data", name).read_text(encoding="utf-8")


def _parse_actors(raw: dict) -> dict[str, Actor]:
    actors: dict[str, Actor] = {}
    for item in raw.get("actors", []) or []:
        role = item.get("role")
        if role not in ROLES:
            raise NotConfigured(f"Peran '{role}' untuk aktor {item.get('id')} tidak dikenal. Pilihan: {ROLES}")
        aid = str(item["id"])
        actors[aid] = Actor(
            id=aid,
            role=role,
            name=item.get("name", ""),
            technical_admin=bool(item.get("technical_admin", False)),
            telegram_user_id=item.get("telegram_user_id"),
            telegram_chat_id=item.get("telegram_chat_id") or item.get("telegram_user_id"),
            wp_user=item.get("wp_user"),
        )
    # operator-ai selalu ada: dipakai skill otomatis (terjadwal, dipicu foto).
    actors.setdefault("operator-ai", Actor(id="operator-ai", role="operator-ai", name="Operator AI"))
    return actors


def load_config(config_dir: str | Path | None = None) -> Config:
    cdir = Path(config_dir or os.environ.get("WPMCP_CONFIG_DIR", "/etc/wp-mcp"))
    data = _deep_merge(DEFAULTS, _load_yaml(cdir / "config.yaml"))
    secrets = parse_env_file(cdir / "secrets.env")

    wl_path = cdir / "cli_whitelist.yaml"
    cli_whitelist = _load_yaml(wl_path) if wl_path.exists() else yaml.safe_load(_packaged_text("cli_whitelist.yaml"))

    pii_path = cdir / "pii_patterns.yaml"
    pii_patterns = _load_yaml(pii_path) if pii_path.exists() else yaml.safe_load(_packaged_text("pii_patterns.yaml"))

    style_path = cdir / "gaya-rumah.md"
    style_guide = style_path.read_text(encoding="utf-8") if style_path.exists() else _packaged_text("gaya-rumah.md")

    cfg = Config(
        data=data,
        config_dir=cdir,
        secrets=secrets,
        actors=_parse_actors(_load_yaml(cdir / "actors.yaml")),
        cli_whitelist=cli_whitelist,
        pii_patterns=pii_patterns,
        style_guide=style_guide,
    )
    if not cfg.get("site.rest_base"):
        cfg.data["site"]["rest_base"] = cfg.get("site.url", "")
    return cfg
