"""Memori Redaksi: ingatan bersama milik website, bukan milik Claude.

Jenis: style (kebiasaan redaksi), story (alur berita bersambung), program, place, reply (jawaban baku).
Nama pejabat dan OPD TIDAK di sini, melainkan di Direktori Resmi (tool directory_*).

Tingkat kepercayaan:
  A  perintah admin/pimpinan          → langsung aktif
  B  berita terbit, pola suntingan    → story langsung aktif; lainnya usulan sampai disahkan
  C  dokumen dinas                    → usulan
  D  bahan informal                   → usulan
Memori 'proposed' tidak pernah dipakai menulis.
"""

from __future__ import annotations

import json
from typing import Any

from ..errors import InvalidInput, NotFound, PIIBlocked
from ..policy import HUMAN_ROLES, ToolContext, tool

KINDS = ("style", "story", "program", "place", "reply")
TTL_DAYS = {"style": None, "story": 365, "program": 365, "place": None, "reply": 180}
SOURCES = {"admin_command": "A", "published_post": "B", "admin_edit_diff": "B", "leader_edit": "B",
           "document": "C", "informal": "D"}


def _valid_until(ctx: ToolContext, kind: str) -> float | None:
    days = TTL_DAYS.get(kind)
    return ctx.now + days * 86400 if days else None


def _row(r: dict[str, Any]) -> dict[str, Any]:
    return {"id": r["id"], "kind": r["kind"], "key": r["key"], "value": json.loads(r["value_json"]),
            "status": r["status"], "source": r["source"], "trust": r["trust"], "hits": r["hits"],
            "used_count": r["used_count"], "valid_until": r["valid_until"], "supersedes": r["supersedes"]}


def _check_value(ctx: ToolContext, kind: str, value: dict[str, Any]) -> None:
    if kind not in KINDS:
        raise InvalidInput(f"Jenis memori '{kind}' tidak dikenal. Pilihan: {', '.join(KINDS)}. "
                           "Nama pejabat/OPD disimpan di Direktori, bukan memori.")
    if not isinstance(value, dict) or not value:
        raise InvalidInput("value harus objek berisi minimal satu bidang.")
    findings = ctx.scanner.scan(json.dumps(value, ensure_ascii=False))
    if findings:
        raise PIIBlocked("Memori tidak boleh berisi data pribadi warga.", detail={"findings": [f.as_dict() for f in findings]})


def _insert(ctx: ToolContext, kind: str, key: str, value: dict, status: str, source: str, source_ref: str | None,
            supersedes: int | None = None) -> int:
    trust = SOURCES.get(source, "D")
    cur = ctx.state.execute(
        "INSERT INTO memory(kind, key, value_json, status, source, source_ref, trust, proposed_by, confirmed_by, "
        "confirmed_at, valid_until, supersedes, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (kind, key, json.dumps(value, ensure_ascii=False), status, source, source_ref, trust, ctx.actor.id,
         ctx.actor.id if status == "active" else None, ctx.now if status == "active" else None,
         _valid_until(ctx, kind), supersedes, ctx.now, ctx.now))
    return int(cur.lastrowid)


def _activate(ctx: ToolContext, kind: str, key: str, value: dict, source: str, source_ref: str | None) -> int:
    old = ctx.state.one("SELECT id FROM memory WHERE kind=? AND key=? AND status='active'", (kind, key))
    if old:
        ctx.state.execute("UPDATE memory SET status='expired', updated_at=? WHERE id=?", (ctx.now, old["id"]))
    return _insert(ctx, kind, key, value, "active", source, source_ref, supersedes=old["id"] if old else None)


def add_story_memory(ctx: ToolContext, post: dict[str, Any], text: str) -> int:
    """Dipanggil otomatis saat berita terbit: berita berikutnya bisa menautkan ke sini."""
    title = post.get("title", {})
    title = title.get("raw") or title.get("rendered") if isinstance(title, dict) else title
    value = {"title": title, "url": post.get("link"), "post_id": post.get("id"), "date": post.get("date"),
             "categories": post.get("categories"), "tags": post.get("tags"), "summary": text[:280]}
    return _insert(ctx, "story", f"post:{post.get('id')}", value, "active", "published_post", str(post.get("id")))


@tool("memory_lookup", level="0", group="memory")
def memory_lookup(ctx: ToolContext, text: str | None = None, kinds: list[str] | None = None, limit: int = 20) -> dict:
    """Cari Memori Redaksi yang AKTIF (sudah disahkan) untuk dipakai menulis: gaya, alur berita bersambung,
    program, tempat, jawaban baku. text dicocokkan ke kunci dan isi."""
    q = "SELECT * FROM memory WHERE status='active' AND (valid_until IS NULL OR valid_until > ?)"
    params: list[Any] = [ctx.now]
    if kinds:
        q += f" AND kind IN ({','.join('?' * len(kinds))})"
        params += list(kinds)
    rows = ctx.state.query(q + " ORDER BY updated_at DESC LIMIT 500", params)
    if text:
        words = {w for w in text.lower().split() if len(w) >= 4}
        def score(r: dict) -> int:
            hay = (r["key"] + " " + r["value_json"]).lower()
            return sum(1 for w in words if w in hay)
        rows = [r for r in rows if score(r) > 0]
        rows.sort(key=score, reverse=True)
    rows = rows[: max(1, min(int(limit), 100))]
    for r in rows:
        ctx.state.execute("UPDATE memory SET used_count=used_count+1, last_used_at=? WHERE id=?", (ctx.now, r["id"]))
    return {"items": [_row(r) for r in rows]}


@tool("memory_propose", level="1", group="memory")
def memory_propose(ctx: ToolContext, kind: str, key: str, value: dict[str, Any], source: str = "informal",
                   source_ref: str | None = None) -> dict:
    """Usulkan memori baru. Usulan yang sama menambah hitungan; tidak dipakai menulis sampai disahkan
    admin-web/pimpinan (memory_confirm). source: admin_command | admin_edit_diff | leader_edit | document | informal."""
    _check_value(ctx, kind, value)
    # Dari pintu model, "perintah admin" hanya menjadi usulan: pengesahan lewat memory_confirm (butuh persetujuan).
    if source == "admin_command" and ctx.actor.role in HUMAN_ROLES and not ctx.model_door:
        mid = _activate(ctx, kind, key, value, source, source_ref)
        return {"id": mid, "status": "active", "note": "Perintah langsung manusia: langsung aktif."}
    if source == "admin_command":
        source = "informal"
    existing = ctx.state.one("SELECT * FROM memory WHERE kind=? AND key=? AND status='proposed'", (kind, key))
    if existing and json.loads(existing["value_json"]) == value:
        ctx.state.execute("UPDATE memory SET hits=hits+1, updated_at=? WHERE id=?", (ctx.now, existing["id"]))
        return {"id": existing["id"], "status": "proposed", "hits": existing["hits"] + 1}
    mid = _insert(ctx, kind, key, value, "proposed", source, source_ref)
    return {"id": mid, "status": "proposed", "hits": 1}


@tool("memory_list_proposals", level="0", roles=HUMAN_ROLES, group="memory")
def memory_list_proposals(ctx: ToolContext, limit: int = 10) -> dict:
    """Usulan memori yang menunggu pengesahan (maks 10 per pesan agar admin tidak kewalahan).
    Usulan berumur lebih dari limits.proposal_ttl_days dihapus otomatis."""
    ttl = int(ctx.cfg.get("limits.proposal_ttl_days", 14)) * 86400
    ctx.state.execute("UPDATE memory SET status='expired' WHERE status='proposed' AND created_at < ?", (ctx.now - ttl,))
    rows = ctx.state.query("SELECT * FROM memory WHERE status='proposed' ORDER BY hits DESC, created_at LIMIT ?",
                           (max(1, min(int(limit), 50)),))
    return {"items": [_row(r) for r in rows]}


@tool("memory_confirm", level="2a", roles=HUMAN_ROLES, group="memory")
def memory_confirm(ctx: ToolContext, memory_id: int, value_override: dict[str, Any] | None = None) -> dict:
    """Sahkan usulan memori (opsional dengan nilai yang dikoreksi). Memori lama dengan kunci sama menjadi expired."""
    row = ctx.state.one("SELECT * FROM memory WHERE id=? AND status='proposed'", (int(memory_id),))
    if not row:
        raise NotFound(f"Usulan memori {memory_id} tidak ditemukan.")
    value = value_override or json.loads(row["value_json"])
    _check_value(ctx, row["kind"], value)
    ctx.state.execute("UPDATE memory SET status='merged', updated_at=? WHERE id=?", (ctx.now, row["id"]))
    mid = _activate(ctx, row["kind"], row["key"], value, row["source"], row["source_ref"])
    return {"id": mid, "status": "active", "from_proposal": row["id"]}


@tool("memory_reject", level="1", roles=HUMAN_ROLES, group="memory")
def memory_reject(ctx: ToolContext, memory_id: int, reason: str | None = None) -> dict:
    """Tolak usulan memori."""
    ctx.state.execute("UPDATE memory SET status='rejected', updated_at=? WHERE id=? AND status='proposed'", (ctx.now, int(memory_id)))
    return {"id": int(memory_id), "status": "rejected", "reason": reason}


@tool("memory_set", level="2a", roles=HUMAN_ROLES, group="memory")
def memory_set(ctx: ToolContext, kind: str, key: str, value: dict[str, Any]) -> dict:
    """Perintah langsung admin/pimpinan ('ingat: ...'): langsung aktif, menggantikan memori lama berkunci sama."""
    _check_value(ctx, kind, value)
    return {"id": _activate(ctx, kind, key, value, "admin_command", None), "status": "active"}


@tool("memory_forget", level="2a", roles=HUMAN_ROLES, group="memory")
def memory_forget(ctx: ToolContext, memory_id: int, reason: str | None = None) -> dict:
    """Lupakan satu memori: isinya dihapus, hanya jejak audit yang tersisa."""
    row = ctx.state.one("SELECT id FROM memory WHERE id=?", (int(memory_id),))
    if not row:
        raise NotFound(f"Memori {memory_id} tidak ditemukan.")
    ctx.state.execute("UPDATE memory SET status='forgotten', value_json='{}', updated_at=? WHERE id=?", (ctx.now, int(memory_id)))
    return {"id": int(memory_id), "status": "forgotten", "reason": reason}


@tool("memory_stale_report", level="0", group="memory")
def memory_stale_report(ctx: ToolContext) -> dict:
    """Memori yang perlu ditanyakan ulang: hampir kedaluwarsa (30 hari) atau tidak dipakai 90 hari."""
    soon = ctx.state.query("SELECT * FROM memory WHERE status='active' AND valid_until IS NOT NULL AND valid_until < ?",
                           (ctx.now + 30 * 86400,))
    unused = ctx.state.query("SELECT * FROM memory WHERE status='active' AND kind != 'story' AND "
                             "COALESCE(last_used_at, created_at) < ?", (ctx.now - 90 * 86400,))
    return {"expiring": [_row(r) for r in soon], "unused_90_days": [_row(r) for r in unused]}
