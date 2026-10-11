"""Delegasi penerbitan berbatas waktu dari pimpinan ke admin-web (mis. saat pimpinan dinas luar)."""

from __future__ import annotations

import json
from typing import Any

from ..errors import InvalidInput, NotFound
from ..policy import ToolContext, tool


def active_delegation_for(ctx: ToolContext, actor_id: str, category_ids: list[int]) -> dict[str, Any] | None:
    rows = ctx.state.query("SELECT * FROM delegations WHERE to_actor=? AND revoked_at IS NULL AND until>? ORDER BY until DESC",
                           (actor_id, ctx.now))
    for r in rows:
        cats = [int(x) for x in json.loads(r["categories_json"] or "[]")]
        if not cats or (category_ids and set(category_ids) <= set(cats)):
            return r
    return None


def _describe_grant(ctx: ToolContext, args: dict) -> dict:
    target = ctx.cfg.actor(args["to_actor"])
    if target.role != "admin-web":
        raise InvalidInput("Delegasi hanya untuk aktor berperan admin-web.")
    days = int(args["days"])
    cats = args.get("categories") or []
    scope = f"kategori {cats}" if cats else "semua kategori"
    return {"summary": f"Delegasikan penerbitan ke {target.label} selama {days} hari ({scope})",
            "impact": [f"{target.label} dapat menerbitkan tanpa menunggu pimpinan", "tercatat di audit, berakhir otomatis"]}


@tool("grant_delegation", level="2b", roles=("pimpinan",), describe_pending=_describe_grant, group="delegation")
def grant_delegation(ctx: ToolContext, to_actor: str, days: int, categories: list[int] | None = None,
                     note: str | None = None) -> dict:
    """Pimpinan memberi delegasi penerbitan ke admin-web, maksimal limits.delegation_max_days hari,
    opsional dibatasi ID kategori. Berakhir otomatis; bisa dicabut lebih awal dengan revoke_delegation."""
    max_days = int(ctx.cfg.get("limits.delegation_max_days", 14))
    days = int(days)
    if not 1 <= days <= max_days:
        raise InvalidInput(f"days harus 1–{max_days}.")
    target = ctx.cfg.actor(to_actor)
    if target.role != "admin-web":
        raise InvalidInput("Delegasi hanya untuk aktor berperan admin-web.")
    until = ctx.now + days * 86400
    cur = ctx.state.execute(
        "INSERT INTO delegations(from_actor, to_actor, categories_json, until, note, created_at) VALUES (?,?,?,?,?,?)",
        (ctx.actor.id, to_actor, json.dumps(categories or []), until, (note or "")[:300], ctx.now))
    ctx.services.notifier.send(target, f"[Humas] Anda menerima delegasi penerbitan selama {days} hari dari {ctx.actor.label}.")
    return {"id": cur.lastrowid, "to_actor": to_actor, "until": int(until), "categories": categories or []}


@tool("revoke_delegation", level="2a", roles=("pimpinan",), group="delegation")
def revoke_delegation(ctx: ToolContext, delegation_id: int) -> dict:
    """Cabut delegasi sebelum waktunya."""
    row = ctx.state.one("SELECT * FROM delegations WHERE id=? AND revoked_at IS NULL", (int(delegation_id),))
    if not row:
        raise NotFound(f"Delegasi {delegation_id} tidak aktif.")
    ctx.state.execute("UPDATE delegations SET revoked_at=?, revoked_by=? WHERE id=?", (ctx.now, ctx.actor.id, int(delegation_id)))
    return {"id": int(delegation_id), "revoked": True}


@tool("list_delegations", level="0", group="delegation")
def list_delegations(ctx: ToolContext, include_expired: bool = False) -> dict:
    """Daftar delegasi aktif (dan yang sudah berakhir bila include_expired)."""
    rows = ctx.state.query("SELECT * FROM delegations ORDER BY created_at DESC LIMIT 100")
    out = []
    for r in rows:
        active = r["revoked_at"] is None and r["until"] > ctx.now
        if active or include_expired:
            out.append({"id": r["id"], "from": r["from_actor"], "to": r["to_actor"], "active": active,
                        "until": int(r["until"]), "categories": json.loads(r["categories_json"]), "note": r["note"]})
    return {"items": out}
