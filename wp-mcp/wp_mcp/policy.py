"""Registri tool dan Dispatcher kebijakan.

Tool sengaja "bodoh": ia hanya mendeklarasikan level risiko dan peran yang boleh memicunya.
Dispatcher yang menegakkan semuanya, di satu tempat:

  peran → izin dinamis (delegasi, kelas komentar) → batas laju → idempotensi
  → pemeriksaan data pribadi → (aksi tertunda + persetujuan) → eksekusi → audit

PINTU MODEL BAHASA vs PINTU MANUSIA
-----------------------------------
Di Claude Code, sesi memakai kunci SSH manusia (admin-web/pimpinan), tetapi yang menekan tombol
adalah model bahasa yang membaca bahan dari luar (caption, PDF, komentar). Karena itu pintu
`claude_code` diperlakukan sebagai PINTU MODEL: setiap aksi level 2a/2b/3 menjadi aksi tertunda yang
hanya bisa disahkan lewat saluran yang tidak bisa dijangkau model:

  - kode sekali pakai yang dikirim ke Telegram manusia itu dan diketik manusia sendiri, atau
  - tombol Setujui di wp-admin → "Persetujuan WP-MCP" dengan login WordPress manusia.

Pintu manusia (cli di server, tombol Telegram gateway, mWPAdmin dengan buka-kunci perangkat) cukup
konfirmasi biasa untuk 2b; level 3 selalu butuh kode OTP.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .audit import AuditLog
from .config import Actor, Config
from .errors import (
    ContentChanged,
    Expired,
    InvalidInput,
    NotAuthorized,
    NotConfigured,
    NotFound,
    PIIBlocked,
    RateLimited,
    WPMCPError,
)
from .notifier import Notifier
from .pii import PIIScanner
from .state import State

LEVELS = ("0", "1", "2a", "2b", "3")
CONFIRM_LEVELS = ("2b", "3")
WRITE_LEVELS = ("1", "2a", "2b", "3")
HUMAN_ROLES = ("admin-web", "pimpinan")
ALL_ROLES = ("operator-ai", "admin-web", "pimpinan")

# Daftar PUTIH pintu manusia. Semua pintu lain (claude_code, dan pintu baru apa pun, termasuk gateway/voice
# yang memakai model bahasa) diperlakukan sebagai pintu model: aksi ≥2a butuh persetujuan di luar percakapan.
HUMAN_DOORS = frozenset({"cli"})
MAX_OTP_ATTEMPTS = 5

LEVEL_DEFAULT_ROLES: dict[str, tuple[str, ...]] = {
    "0": ALL_ROLES,
    "1": ALL_ROLES,
    "2a": HUMAN_ROLES,
    "2b": HUMAN_ROLES,
    "3": HUMAN_ROLES,  # admin-web hanya bila technical_admin: true
}


# ---------------------------------------------------------------------------
# Registri
# ---------------------------------------------------------------------------
@dataclass
class ToolSpec:
    name: str
    fn: Callable[..., Any]
    level: str
    description: str
    roles: tuple[str, ...] | None = None
    authorize: Callable[["ToolContext", dict], None] | None = None
    describe_pending: Callable[["ToolContext", dict], dict] | None = None
    pii_fields: tuple[str, ...] = ()
    group: str = ""

    @property
    def allowed_roles(self) -> tuple[str, ...]:
        return self.roles or LEVEL_DEFAULT_ROLES[self.level]

    @property
    def writes(self) -> bool:
        return self.level in WRITE_LEVELS


REGISTRY: dict[str, ToolSpec] = {}


def tool(
    name: str,
    *,
    level: str,
    roles: tuple[str, ...] | None = None,
    authorize: Callable | None = None,
    describe_pending: Callable | None = None,
    pii_fields: tuple[str, ...] = (),
    group: str = "",
) -> Callable[[Callable], Callable]:
    """Dekorator pendaftaran tool. Fungsi menerima `ctx` sebagai argumen pertama."""
    if level not in LEVELS:
        raise ValueError(f"level tidak dikenal: {level}")

    def deco(fn: Callable) -> Callable:
        doc = inspect.getdoc(fn) or name
        if name in REGISTRY:
            raise ValueError(f"tool ganda: {name}")
        REGISTRY[name] = ToolSpec(name=name, fn=fn, level=level, description=doc, roles=roles,
                                  authorize=authorize, describe_pending=describe_pending,
                                  pii_fields=pii_fields, group=group)
        return fn

    return deco


# ---------------------------------------------------------------------------
# Konteks eksekusi
# ---------------------------------------------------------------------------
@dataclass
class Services:
    """Satu set layanan per proses: konfigurasi, penyimpanan, pintu WordPress, notifikasi."""

    cfg: Config
    state: State
    audit: AuditLog
    scanner: PIIScanner
    notifier: Notifier
    wp: Any = None   # doors.rest.WPRest
    cli: Any = None  # doors.cli.WPCli
    db: Any = None   # doors.db.WPDatabase | None
    osinfo: Any = None
    dispatcher: Any = None
    clock: Callable[[], float] = time.time


@dataclass
class ToolContext:
    services: Services
    actor: Actor
    door: str
    tool: str
    audit_id: str
    warnings: list[dict[str, Any]] = field(default_factory=list)
    confirmed: bool = False  # True saat dieksekusi lewat confirm_action
    pii_findings: list[dict[str, Any]] = field(default_factory=list)

    @property
    def cfg(self) -> Config:
        return self.services.cfg

    @property
    def state(self) -> State:
        return self.services.state

    @property
    def wp(self) -> Any:
        return self.services.wp

    @property
    def cli(self) -> Any:
        return self.services.cli

    @property
    def db(self) -> Any:
        return self.services.db

    @property
    def scanner(self) -> PIIScanner:
        return self.services.scanner

    @property
    def now(self) -> float:
        return self.services.clock()

    @property
    def model_door(self) -> bool:
        return self.door not in HUMAN_DOORS

    def warn(self, code: str, message: str, **extra: Any) -> None:
        self.warnings.append({"code": code, "message": message, **extra})

    def notify_role(self, role: str, text: str) -> int:
        n = 0
        for a in self.cfg.actors_with_role(role):
            if self.services.notifier.send(a, text):
                n += 1
        return n


# ---------------------------------------------------------------------------
# Pembantu
# ---------------------------------------------------------------------------
def content_hash(*parts: Any) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _otp_hash(code: str, action_id: str) -> str:
    return hashlib.sha256(f"{action_id}:{code}".encode()).hexdigest()


def _squash(value: Any, limit: int = 2000) -> Any:
    """Rapikan argumen untuk dibaca manusia: spasi beruntun diciutkan, teks panjang ditandai jelas."""
    if isinstance(value, str):
        v = " ".join(value.split())
        return v if len(v) <= limit else v[:limit] + f" …[+{len(v) - limit} karakter tidak ditampilkan]"
    if isinstance(value, dict):
        return {k: _squash(v, limit) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_squash(v, limit) for v in value]
    return value


def generic_description(spec_name: str, args: dict) -> dict:
    shown = _squash(args, 300)
    parts = [f"{k}={json.dumps(v, ensure_ascii=False, default=str)}" for k, v in shown.items()]
    return {"summary": f"{spec_name}: " + "; ".join(parts), "readback": _squash(args)}


def _iter_strings(value: Any, prefix: str):
    """Semua string di dalam nilai bersarang (str, list, dict) beserta jalurnya."""
    if isinstance(value, str):
        yield prefix, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _iter_strings(v, f"{prefix}.{k}")
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            yield from _iter_strings(v, f"{prefix}[{i}]")


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
class Dispatcher:
    def __init__(self, services: Services, registry: dict[str, ToolSpec] | None = None):
        self.s = services
        self.registry = registry if registry is not None else REGISTRY

    # --- envelope ---------------------------------------------------------
    @staticmethod
    def _ok(spec: ToolSpec, ctx: ToolContext, data: Any, pending: dict | None = None) -> dict:
        return {"ok": True, "tool": spec.name, "level": spec.level, "actor": ctx.actor.id,
                "data": data, "warnings": ctx.warnings, "pending_action": pending, "audit_id": ctx.audit_id}

    @staticmethod
    def _err(name: str, actor: str, audit_id: str, exc: WPMCPError) -> dict:
        return {"ok": False, "tool": name, "actor": actor, "audit_id": audit_id,
                "error": {"code": exc.code, "message": exc.message, "detail": exc.detail}}

    # --- pemeriksaan ------------------------------------------------------
    def check_role(self, spec: ToolSpec, ctx: ToolContext, args: dict) -> None:
        actor = ctx.actor
        allowed = spec.allowed_roles
        if actor.role not in allowed:
            raise NotAuthorized(
                f"Peran {actor.role} tidak boleh menjalankan {spec.name} (level {spec.level}). "
                f"Yang berwenang: {', '.join(allowed)}.",
                detail={"required_roles": list(allowed), "actor_role": actor.role},
            )
        if spec.level == "3" and actor.role == "admin-web" and not actor.technical_admin:
            raise NotAuthorized(
                f"{spec.name} adalah aksi sistem (level 3). Admin-web hanya boleh bila ditunjuk "
                "pimpinan sebagai admin teknis (technical_admin: true di actors.yaml).",
                detail={"required": "pimpinan atau admin-web technical_admin"},
            )
        if spec.authorize:
            spec.authorize(ctx, args)

    def check_rate(self, ctx: ToolContext) -> None:
        limit = int(self.s.cfg.get("limits.writes_per_10min", 30))
        n = self.s.state.writes_since(ctx.actor.id, ctx.now - 600)
        if n >= limit:
            for a in self.s.cfg.actors_with_role("pimpinan"):
                self.s.notifier.send(a, f"[WP-MCP] Batas laju tercapai untuk {ctx.actor.label}: {n} aksi tulis dalam 10 menit.")
            raise RateLimited(f"Batas {limit} aksi tulis per 10 menit tercapai untuk {ctx.actor.id}. "
                              "Berhenti dan minta manusia memeriksa.", detail={"count": n, "limit": limit})

    def check_pii(self, spec: ToolSpec, ctx: ToolContext, args: dict) -> None:
        if not self.s.cfg.get("privacy.pii_scan", True) or not spec.pii_fields:
            return
        findings: list[dict] = []
        for fld in spec.pii_fields:
            for path, text in _iter_strings(args.get(fld), fld):
                findings += [f.as_dict(path) for f in self.s.scanner.scan(text)]
        if not findings:
            return
        if args.get("confirm_public_pii") and ctx.actor.role in HUMAN_ROLES:
            ctx.warn("PII_CONFIRMED_PUBLIC", f"{len(findings)} pola data pribadi dikonfirmasi publik oleh {ctx.actor.label}.")
            ctx.pii_findings = findings  # dari pintu model, ini menaikkan aksi menjadi tertunda
            return
        raise PIIBlocked(
            f"Isi memuat {len(findings)} pola data pribadi. Tunjukkan ke admin-web atau pimpinan; "
            "ulangi dengan confirm_public_pii=true oleh manusia bila memang untuk publik.",
            detail={"findings": findings},
        )

    # --- jalur utama ------------------------------------------------------
    def call(self, actor_id: str, name: str, args: dict[str, Any] | None = None, *, door: str = "claude_code") -> dict:
        # Parameter berawalan "_" hanya boleh diisi oleh kebijakan (mis. _delegation_id), tidak dari pemanggil.
        args = {k: v for k, v in (args or {}).items() if not str(k).startswith("_")}
        if name == "confirm_action":
            if not args.get("action_id"):
                return {"ok": False, "tool": name, "error": {"code": "INVALID_INPUT", "message": "action_id wajib."}}
            return self.confirm(actor_id, args["action_id"], args.get("otp"), door=door)
        audit_id = self.s.audit.new_id()
        spec = self.registry.get(name)
        started = time.time()
        if spec is None:
            return self._err(name, actor_id, audit_id, NotFound(f"Tool {name} tidak ada.",
                                                                detail={"tools": sorted(self.registry)}))
        try:
            actor = self.s.cfg.actor(actor_id)
        except WPMCPError as exc:
            return self._err(name, actor_id, audit_id, exc)
        ctx = ToolContext(services=self.s, actor=actor, door=door, tool=name, audit_id=audit_id)
        pending: dict | None = None
        try:
            self.check_role(spec, ctx, args)
            if spec.writes:
                self.check_rate(ctx)
            idem_key = args.pop("idempotency_key", None)
            if idem_key:
                cached = self.s.state.idem_get(idem_key, actor.id, name)
                if cached is not None:
                    cached = dict(cached)
                    cached["warnings"] = list(cached.get("warnings", [])) + [
                        {"code": "IDEMPOTENT_REPLAY", "message": "Hasil pertama dikembalikan; tidak ditulis ulang."}]
                    return cached
            self.check_pii(spec, ctx, args)
            args.pop("confirm_public_pii", None)
            # Hak khusus manusia yang diminta dari pintu model (data pribadi untuk publik, HTML mentah)
            # tidak boleh jalan langsung: dinaikkan menjadi aksi tertunda dengan persetujuan di luar percakapan.
            elevated = ctx.model_door and (bool(ctx.pii_findings) or bool(args.get("allow_html")))

            if spec.level in CONFIRM_LEVELS or (ctx.model_door and spec.level == "2a") or elevated:
                pending = self._create_pending(spec, ctx, args, elevated=elevated)
                self.s.state.record_write(actor.id, ctx.now)
                result = self._ok(spec, ctx, None, pending)
            else:
                data = self._invoke(spec, ctx, args)
                if spec.writes:
                    self.s.state.record_write(actor.id, ctx.now)
                result = self._ok(spec, ctx, data)
            if idem_key:
                self.s.state.idem_put(idem_key, actor.id, name, result)
            self._audit(ctx, spec, args, "pending" if pending else "ok", started, pending=pending)
            return result
        except WPMCPError as exc:
            self._audit(ctx, spec, args, exc.code, started)
            return self._err(name, actor.id, audit_id, exc)
        except TypeError as exc:
            err = InvalidInput(f"Parameter tidak sesuai untuk {name}: {exc}")
            self._audit(ctx, spec, args, err.code, started)
            return self._err(name, actor.id, audit_id, err)

    def _invoke(self, spec: ToolSpec, ctx: ToolContext, args: dict) -> Any:
        sig = inspect.signature(spec.fn)
        accepted = {k: v for k, v in args.items() if k in sig.parameters}
        unknown = sorted(set(args) - set(accepted))
        if unknown:
            raise InvalidInput(f"Parameter tidak dikenal untuk {spec.name}: {', '.join(unknown)}")
        return spec.fn(ctx, **accepted)

    def _audit(self, ctx: ToolContext, spec: ToolSpec, args: dict, result: str, started: float, *,
               pending: dict | None = None, confirmation: dict | None = None) -> None:
        objects = {k: v for k, v in args.items() if k in ("post_id", "id", "media_id", "comment_id", "reply_id", "action_id")}
        entry = {
            "audit_id": ctx.audit_id, "actor": ctx.actor.id, "role": ctx.actor.role, "door": ctx.door,
            "acting_as": "operator-ai" if ctx.model_door else ctx.actor.role,
            "tool": spec.name, "level": spec.level, "parameters": args, "result": result,
            "objects": objects, "duration_ms": int((time.time() - started) * 1000),
        }
        if pending:
            entry["pending_action_id"] = pending["id"]
        if confirmation:
            entry["confirmation"] = confirmation
        self.s.audit.write(entry)

    # --- aksi tertunda ----------------------------------------------------
    def _push_to_wp_admin(self, action: dict) -> bool:
        """Kirim ringkasan aksi ke halaman Persetujuan WP-MCP di wp-admin (plugin bridge)."""
        if not self.s.cfg.get("approvals.wp_admin", True) or self.s.wp is None:
            return False
        try:
            self.s.wp.post("/wpmcp/v1/pending", action)
            return True
        except WPMCPError:
            return False

    def _create_pending(self, spec: ToolSpec, ctx: ToolContext, args: dict, elevated: bool = False) -> dict:
        desc = spec.describe_pending(ctx, args) if spec.describe_pending else generic_description(spec.name, args)
        if elevated:
            extra = []
            if ctx.pii_findings:
                extra.append("DATA PRIBADI akan tayang publik: " + ", ".join(
                    f"{f['label']} {f['sample']} di {f['field']}" for f in ctx.pii_findings[:10]))
            if args.get("allow_html"):
                extra.append("HTML MENTAH diizinkan dalam isi")
            desc = dict(desc)
            desc["summary"] = " | ".join(extra) + " | " + desc.get("summary", spec.name)
            desc["impact"] = list(desc.get("impact", [])) + extra
            desc.setdefault("readback", _squash(args))
        minutes = int(self.s.cfg.get("limits.pending_action_minutes", 15))
        now = ctx.now
        action_id = "act_" + uuid.uuid4().hex[:10]
        summary = desc.get("summary") or generic_description(spec.name, args)["summary"]
        impact = desc.get("impact", [])

        oob = ctx.model_door                       # persetujuan di luar percakapan
        otp_required = spec.level == "3" and self.s.cfg.get("otp.channel", "telegram") != "none"
        can_telegram = bool(self.s.notifier.enabled and (ctx.actor.telegram_chat_id or ctx.actor.telegram_user_id))
        channels: list[str] = []

        otp_hash = otp_exp = None
        if otp_required or (oob and can_telegram):
            if not can_telegram:
                raise NotConfigured(
                    "Aksi level 3 butuh kode sekali pakai lewat Telegram, tetapi Telegram belum dikonfigurasi untuk "
                    "aktor ini. Atur notify.telegram dan telegram_user_id, atau secara sadar set otp.channel: none.")
            code = f"{secrets.randbelow(10**6):06d}"
            otp_hash = _otp_hash(code, action_id)
            otp_exp = now + 60 * int(self.s.cfg.get("limits.otp_minutes", 5))
            rb = json.dumps(desc.get("readback"), ensure_ascii=False, default=str)[:1500] if desc.get("readback") else ""
            self.s.notifier.send(ctx.actor, f"[WP-MCP] {summary}\n{rb}\nKode persetujuan {action_id}: {code}\n"
                                            f"Berlaku {self.s.cfg.get('limits.otp_minutes', 5)} menit. Ketik kode ini "
                                            "sendiri bila Anda memang menyetujui; jangan bagikan.")
            channels.append("otp")

        expires = now + 60 * minutes
        public = {"id": action_id, "tool": spec.name, "level": spec.level, "summary": summary, "impact": impact,
                  "readback": desc.get("readback"), "requested_by": ctx.actor.id, "door": ctx.door,
                  "expires_at": int(expires)}
        if oob and not otp_required and self._push_to_wp_admin(public):
            channels.append("wp_admin")
        if oob and not channels:
            raise NotConfigured(
                "Aksi ini butuh persetujuan manusia di luar percakapan, tetapi belum ada salurannya: aktifkan Telegram "
                "(kode persetujuan) atau plugin wp-mcp-bridge (halaman Persetujuan WP-MCP di wp-admin).")

        self.s.state.execute(
            "INSERT INTO pending_actions(id, tool, level, actor, args_json, summary, impact_json, content_hash, "
            "target_ref, created_at, expires_at, otp_hash, otp_expires_at, door, oob, channels_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (action_id, spec.name, spec.level, ctx.actor.id, json.dumps(args, ensure_ascii=False, default=str),
             summary, json.dumps(impact, ensure_ascii=False), desc.get("content_hash"), desc.get("target_ref"),
             now, expires, otp_hash, otp_exp, ctx.door, int(oob), json.dumps(channels)),
        )
        how = {
            "otp": "ketik kode persetujuan yang dikirim ke Telegram Anda",
            "wp_admin": "atau setujui di wp-admin → Persetujuan WP-MCP",
        }
        if oob:
            instruction = ("Bacakan ringkasan ini ke pengguna. Persetujuan HARUS datang dari manusia di luar percakapan: "
                           + "; ".join(how[c] for c in channels)
                           + ". Setelah itu panggil confirm_action(action_id"
                           + (", otp=<kode yang diketik pengguna>" if "otp" in channels else "") + ").")
        else:
            instruction = "Konfirmasi dengan confirm_action" + (" dan kode OTP dari Telegram." if otp_required else ".")
        return {"id": action_id, "summary": summary, "impact": impact, "readback": desc.get("readback"),
                "expires_in_minutes": minutes, "needs_otp": otp_required, "approval_channels": channels,
                "how_to_confirm": instruction}

    def _check_otp(self, row: dict, otp: str) -> bool:
        if row["otp_expires_at"] and self.s.clock() > row["otp_expires_at"]:
            raise Expired("Kode kedaluwarsa. Buat ulang aksinya.")
        if secrets.compare_digest(_otp_hash(str(otp).strip(), row["id"]), row["otp_hash"] or ""):
            return True
        attempts = int(row.get("otp_attempts") or 0) + 1
        if attempts >= MAX_OTP_ATTEMPTS:
            self.s.state.execute("UPDATE pending_actions SET status='failed', otp_attempts=? WHERE id=?", (attempts, row["id"]))
            raise NotAuthorized(f"Kode salah {attempts} kali; aksi {row['id']} dibatalkan. Buat ulang aksinya.")
        self.s.state.execute("UPDATE pending_actions SET otp_attempts=? WHERE id=?", (attempts, row["id"]))
        raise NotAuthorized(f"Kode salah ({attempts}/{MAX_OTP_ATTEMPTS}).")

    def _wp_admin_approval(self, row: dict) -> Actor | None:
        """Cari persetujuan dari halaman wp-admin; kembalikan aktor manusia yang menyetujui."""
        try:
            rec = self.s.wp.get(f"/wpmcp/v1/approvals/{row['id']}").data or {}
        except WPMCPError:
            return None
        decision = rec.get("decision")
        if decision not in ("approved", "rejected"):
            return None
        login = rec.get("user_login")
        actor = next((a for a in self.s.cfg.actors.values()
                      if a.wp_user and a.wp_user == login and a.role in HUMAN_ROLES), None)
        if actor is None:
            raise NotAuthorized(f"Akun WordPress '{login}' tidak dipetakan ke aktor mana pun (wp_user di actors.yaml); "
                                "keputusannya diabaikan.")
        if decision == "rejected":
            self.s.state.execute("UPDATE pending_actions SET status='rejected' WHERE id=?", (row["id"],))
            raise NotAuthorized(f"Aksi {row['id']} ditolak di wp-admin oleh {actor.label}.")
        return actor

    def confirm(self, actor_id: str, action_id: str, otp: str | None = None, *, door: str = "claude_code") -> dict:
        audit_id = self.s.audit.new_id()
        started = time.time()
        row = self.s.state.one("SELECT * FROM pending_actions WHERE id=?", (action_id,))
        try:
            actor = self.s.cfg.actor(actor_id)
            if not row:
                raise NotFound(f"Aksi {action_id} tidak ditemukan.")
            spec = self.registry[row["tool"]]
        except WPMCPError as exc:
            return self._err("confirm_action", actor_id, audit_id, exc)
        ctx = ToolContext(services=self.s, actor=actor, door=door, tool=spec.name, audit_id=audit_id, confirmed=True)
        args = json.loads(row["args_json"])
        via = "direct"
        try:
            if actor.role == "operator-ai":
                raise NotAuthorized("operator-ai tidak pernah boleh mengonfirmasi aksi. Konfirmasi harus oleh manusia.")
            if row["status"] != "pending":
                raise Expired(f"Aksi {action_id} berstatus {row['status']}; tidak bisa dikonfirmasi lagi.")
            if ctx.now > row["expires_at"]:
                self.s.state.execute("UPDATE pending_actions SET status='expired' WHERE id=?", (action_id,))
                raise Expired(f"Aksi {action_id} kedaluwarsa. Buat ulang.")

            channels = json.loads(row.get("channels_json") or "[]")
            needs_external = bool(row.get("oob")) or ctx.model_door or bool(row["otp_hash"] and spec.level == "3")
            if needs_external:
                approver: Actor | None = None
                if otp and row["otp_hash"] and self._check_otp(row, otp):
                    approver, via = self.s.cfg.actor(row["actor"]), "otp"
                elif spec.level != "3" and "wp_admin" in channels:
                    approver = self._wp_admin_approval(row)
                    via = "wp_admin" if approver else via
                if approver is None:
                    ways = []
                    if "otp" in channels:
                        ways.append("kode dari Telegram yang diketik pengguna (otp)")
                    if "wp_admin" in channels and spec.level != "3":
                        ways.append("tombol Setujui di wp-admin → Persetujuan WP-MCP")
                    raise NotAuthorized("Belum ada persetujuan manusia di luar percakapan. Diperlukan: "
                                        + (" atau ".join(ways) or "kode OTP") + ".",
                                        detail={"channels": channels})
                # yang mengeksekusi adalah manusia yang menyetujui
                ctx = ToolContext(services=self.s, actor=approver, door=door, tool=spec.name, audit_id=audit_id, confirmed=True)

            self.check_role(spec, ctx, args)
            if row["content_hash"] and spec.describe_pending:
                fresh = spec.describe_pending(ctx, args).get("content_hash")
                if fresh and fresh != row["content_hash"]:
                    self.s.state.execute("UPDATE pending_actions SET status='stale' WHERE id=?", (action_id,))
                    raise ContentChanged("Konten berubah sejak aksi ini dibuat. Tinjau ulang lalu buat aksi baru.",
                                         detail={"was": row["content_hash"], "now": fresh})
            self.check_rate(ctx)
            # klaim atomik: dua konfirmasi bersamaan tidak boleh sama-sama mengeksekusi
            claimed = self.s.state.execute(
                "UPDATE pending_actions SET status='executing' WHERE id=? AND status='pending'", (action_id,)).rowcount
            if claimed != 1:
                raise Expired(f"Aksi {action_id} sedang atau sudah diproses.")
            try:
                data = self._invoke(spec, ctx, args)
            except Exception:
                self.s.state.execute("UPDATE pending_actions SET status='failed' WHERE id=?", (action_id,))
                raise
            self.s.state.record_write(ctx.actor.id, ctx.now)
            self.s.state.execute(
                "UPDATE pending_actions SET status='confirmed', confirmed_by=?, confirmed_at=?, result_json=? WHERE id=?",
                (ctx.actor.id, ctx.now, json.dumps(data, ensure_ascii=False, default=str), action_id))
            self._audit(ctx, spec, args, "ok", started, confirmation={
                "action_id": action_id, "requested_by": row["actor"], "requested_door": row.get("door"),
                "confirmed_by": ctx.actor.id, "via": via, "door": door})
            return self._ok(spec, ctx, data)
        except WPMCPError as exc:
            self._audit(ctx, spec, args, exc.code, started,
                        confirmation={"action_id": action_id, "attempt_by": actor.id, "via": via})
            return self._err(spec.name, actor.id, audit_id, exc)

    def cancel(self, actor_id: str, action_id: str) -> dict:
        row = self.s.state.one("SELECT * FROM pending_actions WHERE id=?", (action_id,))
        if not row or row["status"] != "pending":
            return {"ok": False, "error": {"code": "NOT_FOUND", "message": f"Tidak ada aksi tertunda {action_id}."}}
        actor = self.s.cfg.actor(actor_id)
        if actor.id != row["actor"] and actor.role != "pimpinan":
            return {"ok": False, "error": {"code": "NOT_AUTHORIZED",
                                           "message": "Hanya pembuat aksi atau pimpinan yang boleh membatalkan."}}
        self.s.state.execute("UPDATE pending_actions SET status='cancelled' WHERE id=?", (action_id,))
        self.s.audit.write({"audit_id": self.s.audit.new_id(), "actor": actor.id, "tool": "cancel_action",
                            "parameters": {"action_id": action_id}, "result": "ok"})
        return {"ok": True, "data": {"cancelled": action_id}}

    def list_pending(self, actor_id: str | None = None) -> list[dict]:
        now = self.s.clock()
        rows = self.s.state.query("SELECT * FROM pending_actions WHERE status='pending' ORDER BY created_at")
        out = []
        for r in rows:
            if now > r["expires_at"]:
                self.s.state.execute("UPDATE pending_actions SET status='expired' WHERE id=?", (r["id"],))
                continue
            if actor_id and r["actor"] != actor_id:
                continue
            out.append({"id": r["id"], "tool": r["tool"], "level": r["level"], "requested_by": r["actor"],
                        "summary": r["summary"], "impact": json.loads(r["impact_json"]),
                        "approval_channels": json.loads(r.get("channels_json") or "[]"),
                        "expires_in_minutes": max(0, int((r["expires_at"] - now) / 60))})
        return out
