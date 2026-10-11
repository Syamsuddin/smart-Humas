"""Tool komentar: daftar (identitas komentator dimasker), draft balasan, spam, persetujuan berjenjang.

Kelas balasan dan siapa menyetujui:
  pertanyaan_layanan, apresiasi, di_luar_kewenangan → admin-web atau pimpinan
  aduan, koreksi_fakta                              → pimpinan
  spam → mark_spam; provokasi/SARA → tidak dibalas.
"""

from __future__ import annotations

from typing import Any, Literal

from ..errors import InvalidInput, NotAuthorized
from ..markdown_blocks import plain_text
from ..pii import hash_identity
from ..policy import HUMAN_ROLES, ToolContext, tool

ReplyClass = Literal["pertanyaan_layanan", "apresiasi", "di_luar_kewenangan", "aduan", "koreksi_fakta"]
LEADER_CLASSES = {"aduan", "koreksi_fakta"}


def _me(ctx: ToolContext) -> int | None:
    try:
        return ctx.wp.get("/wp/v2/users/me").data.get("id")
    except Exception:
        return None


def _mask(ctx: ToolContext, c: dict[str, Any]) -> dict[str, Any]:
    text = plain_text((c.get("content") or {}).get("raw") or (c.get("content") or {}).get("rendered", ""))
    masked = ctx.cfg.get("privacy.mask_commenter", True)
    return {
        "id": c["id"], "post": c.get("post"), "parent": c.get("parent"), "status": c.get("status"),
        "date": c.get("date"), "author_name": c.get("author_name"),
        "author_ref": hash_identity(c.get("author_email")) if masked else c.get("author_email"),
        "content": ctx.scanner.mask(text) if masked else text,
        "reply_class": (c.get("meta") or {}).get("_wpmcp_reply_class") or None,
    }


@tool("list_comments", level="0", group="comments")
def list_comments(ctx: ToolContext, status: Literal["hold", "approve", "all"] = "all", post_id: int | None = None,
                  since: str | None = None, unanswered_only: bool = True, limit: int = 30) -> dict:
    """Daftar komentar warga. Email/IP komentator diganti hash dan data pribadi di isi komentar disamarkan
    sebelum keluar dari server. unanswered_only membuang komentar yang sudah punya balasan (atau draft balasan)."""
    params: dict[str, Any] = {"context": "edit", "per_page": max(1, min(int(limit), 100)), "post": post_id,
                              "after": since, "orderby": "date", "order": "desc"}
    statuses = ["hold", "approve"] if status == "all" else [status]
    me = _me(ctx)
    items: list[dict] = []
    for st in statuses:
        items += [x for x in (ctx.wp.get("/wp/v2/comments", status=st, **params).data or [])]
    ours = [x for x in items if me and x.get("author") == me]
    citizens = [x for x in items if not (me and x.get("author") == me)]
    replied: dict[int, list[int]] = {}
    if me:
        for st in ("hold", "approve"):
            for r in ctx.wp.get("/wp/v2/comments", status=st, author=me, context="edit", per_page=100).data or []:
                replied.setdefault(r.get("parent"), []).append(r["id"])
    out = []
    for cm in citizens:
        m = _mask(ctx, cm)
        m["our_replies"] = replied.get(cm["id"], [])
        if unanswered_only and m["our_replies"]:
            continue
        out.append(m)
    return {"items": out, "draft_replies_waiting": [x["id"] for x in ours if x.get("status") == "hold"]}


@tool("draft_reply", level="1", pii_fields=("content",), group="comments")
def draft_reply(ctx: ToolContext, comment_id: int, content: str, reply_class: ReplyClass,
                idempotency_key: str | None = None, confirm_public_pii: bool = False) -> dict:
    """Siapkan draft balasan (status 'hold', belum tampil). reply_class menentukan siapa yang menyetujui:
    aduan/koreksi_fakta → pimpinan; lainnya → admin-web."""
    parent = ctx.wp.get(f"/wp/v2/comments/{int(comment_id)}", context="edit").data
    words = len(content.split())
    if words > 120:
        ctx.warn("REPLY_LONG", f"Balasan {words} kata; pedoman 2–4 kalimat.")
    body = {"post": parent["post"], "parent": int(comment_id), "content": content, "status": "hold",
            "author_name": ctx.cfg.get("reply.signature", "Admin Website"),
            "meta": {"_wpmcp_reply_class": reply_class, "_wpmcp_drafted_by": f"operator-ai via {ctx.actor.id}"}}
    reply = ctx.wp.post("/wp/v2/comments", body).data
    approver = "pimpinan" if reply_class in LEADER_CLASSES else "admin-web"
    return {"reply_id": reply["id"], "status": "hold", "reply_class": reply_class, "approver": approver}


@tool("mark_spam", level="1", group="comments")
def mark_spam(ctx: ToolContext, comment_id: int) -> dict:
    """Tandai komentar warga yang MASIH TERTAHAN (hold) sebagai spam. Komentar yang sudah tampil tidak bisa
    disembunyikan lewat tool ini (keputusan moderasi publik ada di admin-web)."""
    cm = ctx.wp.get(f"/wp/v2/comments/{int(comment_id)}", context="edit").data
    me = _me(ctx)
    if cm.get("status") != "hold":
        raise InvalidInput("Hanya komentar berstatus tertahan (hold) yang bisa ditandai spam lewat WP-MCP.")
    if me and cm.get("author") == me:
        raise InvalidInput("Draft balasan WP-MCP tidak ditandai spam; hapus draft lewat wp-admin.")
    ctx.wp.post(f"/wp/v2/comments/{int(comment_id)}", {"status": "spam"})
    return {"id": int(comment_id), "status": "spam"}


# Kata yang menandakan aduan/keluhan. Bila muncul di komentar warga, balasan butuh pimpinan
# apa pun kelas yang dipilih penyusun (kelas dipilih model, jadi tidak dipercaya sendirian).
COMPLAINT_WORDS = ("kecewa", "lambat", "lamban", "pungli", "pungutan", "aduan", "mengadu", "lapor", "keluh",
                   "komplain", "buruk", "tidak dilayani", "dipersulit", "calo", "suap", "korupsi", "salah",
                   "keliru", "tidak benar", "hoaks", "bohong", "protes", "marah", "parah", "rusak")


def _parent_text(ctx: ToolContext, reply: dict[str, Any]) -> str:
    if not reply.get("parent"):
        return ""
    parent = ctx.wp.get(f"/wp/v2/comments/{int(reply['parent'])}", context="edit").data
    return plain_text((parent.get("content") or {}).get("raw") or (parent.get("content") or {}).get("rendered", ""))


def _effective_class(ctx: ToolContext, reply: dict[str, Any]) -> tuple[str, bool]:
    cls = (reply.get("meta") or {}).get("_wpmcp_reply_class") or ""
    parent = _parent_text(ctx, reply).lower()
    flagged = any(w in parent for w in COMPLAINT_WORDS)
    return cls, flagged


def _authorize_reply(ctx: ToolContext, args: dict) -> None:
    reply = ctx.wp.get(f"/wp/v2/comments/{int(args['reply_id'])}", context="edit").data
    cls, flagged = _effective_class(ctx, reply)
    if not cls:
        raise InvalidInput("Komentar ini bukan draft balasan WP-MCP.")
    if (cls in LEADER_CLASSES or flagged) and ctx.actor.role != "pimpinan":
        why = f"kelas '{cls}'" if cls in LEADER_CLASSES else "komentar warga mengandung kata keluhan"
        raise NotAuthorized(f"Balasan ini disetujui pimpinan ({why}).", detail={"reply_class": cls, "complaint_flag": flagged})


def _describe_reply(ctx: ToolContext, args: dict) -> dict:
    reply = ctx.wp.get(f"/wp/v2/comments/{int(args['reply_id'])}", context="edit").data
    text = plain_text((reply.get("content") or {}).get("raw") or "")
    cls, flagged = _effective_class(ctx, reply)
    parent = ctx.scanner.mask(_parent_text(ctx, reply))
    from ..policy import content_hash
    return {"summary": f"Kirim balasan #{reply['id']} ({cls}) ke komentar #{reply.get('parent')}: \"{text[:140]}\"",
            "impact": ["balasan tampil publik di bawah berita"] + (["komentar warga juga disetujui tampil"] if args.get("approve_parent") else []),
            "content_hash": content_hash(text), "target_ref": f"comment:{reply['id']}",
            "readback": {"reply": text, "reply_class": cls, "citizen_comment": parent[:400], "complaint_flag": flagged}}


@tool("send_reply", level="2b", roles=HUMAN_ROLES, authorize=_authorize_reply, describe_pending=_describe_reply, group="comments")
def send_reply(ctx: ToolContext, reply_id: int, approve_parent: bool = False) -> dict:
    """Setujui dan tampilkan draft balasan. approve_parent=true sekaligus menampilkan komentar warga yang dibalas."""
    reply = ctx.wp.post(f"/wp/v2/comments/{int(reply_id)}", {"status": "approve"}).data
    if approve_parent and reply.get("parent"):
        ctx.wp.post(f"/wp/v2/comments/{int(reply['parent'])}", {"status": "approve"})
    return {"reply_id": int(reply_id), "status": "approved", "parent_approved": bool(approve_parent)}


def _describe_approve_comment(ctx: ToolContext, args: dict) -> dict:
    cm = ctx.wp.get(f"/wp/v2/comments/{int(args['comment_id'])}", context="edit").data
    text = ctx.scanner.mask(plain_text((cm.get("content") or {}).get("raw") or ""))
    return {"summary": f"Tampilkan komentar warga #{cm['id']}: \"{text[:140]}\"", "impact": ["komentar tampil publik"]}


@tool("approve_comment", level="2b", roles=HUMAN_ROLES, describe_pending=_describe_approve_comment, group="comments")
def approve_comment(ctx: ToolContext, comment_id: int) -> dict:
    """Tampilkan komentar warga yang tertahan moderasi."""
    ctx.wp.post(f"/wp/v2/comments/{int(comment_id)}", {"status": "approve"})
    return {"id": int(comment_id), "status": "approved"}
