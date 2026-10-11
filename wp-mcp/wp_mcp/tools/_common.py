"""Pembantu bersama untuk tool: akses post, status alur kerja, meta, Direktori, media."""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Literal

from ..errors import InvalidInput, NotFound, WorkflowError
from ..markdown_blocks import plain_text
from ..policy import ToolContext, content_hash

PostType = Literal["post", "page"]
ENDPOINT = {"post": "/wp/v2/posts", "page": "/wp/v2/pages"}

# Status alur kerja (meta _wpmcp_state) dan status WordPress padanannya
STATE_DRAFT = "draft"
STATE_REVISI = "revisi"
STATE_READY = "siap_tayang"
STATE_PUBLISHED = "published"
EDITABLE_STATES = (STATE_DRAFT, STATE_REVISI)

META_KEYS = (
    "_wpmcp_state", "_wpmcp_drafted_by", "_wpmcp_revised_by", "_wpmcp_revision_requests", "_wpmcp_submitted_by",
    "_wpmcp_submitted_at", "_wpmcp_reviewer_note", "_wpmcp_leader_edits", "_wpmcp_approved_by",
    "_wpmcp_published_by", "_wpmcp_delegation_id", "_wpmcp_corrections", "_wpmcp_withdrawn", "_wpmcp_source_note",
)

MONTHS_ID = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September",
             "Oktober", "November", "Desember"]
DAYS_ID = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]


def endpoint(post_type: str) -> str:
    if post_type not in ENDPOINT:
        raise InvalidInput("type harus 'post' atau 'page'.")
    return ENDPOINT[post_type]


def fetch_post(ctx: ToolContext, post_id: int, post_type: str = "post") -> dict[str, Any]:
    try:
        return ctx.wp.get(f"{endpoint(post_type)}/{int(post_id)}", context="edit").data
    except Exception as exc:  # WPRejected 404 → NotFound yang jelas
        if getattr(exc, "detail", {}).get("http_status") == 404:
            raise NotFound(f"{post_type} #{post_id} tidak ditemukan.") from None
        raise


def raw(field: Any) -> str:
    if isinstance(field, dict):
        return field.get("raw") if field.get("raw") is not None else field.get("rendered", "")
    return field or ""


def meta(post: dict[str, Any]) -> dict[str, Any]:
    return post.get("meta") or {}


def meta_json(post: dict[str, Any], key: str) -> list:
    val = meta(post).get(key)
    if not val:
        return []
    try:
        data = json.loads(val) if isinstance(val, str) else val
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else [data]


def state_of(post: dict[str, Any]) -> str:
    """Status alur kerja. Status WordPress yang sesungguhnya selalu menang atas meta, sehingga post yang
    diterbitkan/dijadikan privat lewat wp-admin tidak pernah dianggap draft yang boleh ditimpa."""
    wp_status = post.get("status")
    if wp_status in ("publish", "future", "private"):
        return STATE_PUBLISHED
    if wp_status == "pending":
        return STATE_READY
    if wp_status == "trash":
        return "trash"
    st = meta(post).get("_wpmcp_state")
    if st in (STATE_DRAFT, STATE_REVISI):
        return st
    # meta menyebut siap_tayang/published tetapi WordPress berkata draft: diubah di luar WP-MCP → revisi
    return STATE_REVISI if st else STATE_DRAFT


def post_hash(post: dict[str, Any]) -> str:
    return content_hash(raw(post.get("title")), raw(post.get("content")), raw(post.get("excerpt")),
                        post.get("featured_media"), sorted(post.get("categories") or []), sorted(post.get("tags") or []))


def require_state(post: dict[str, Any], allowed: tuple[str, ...], action: str) -> str:
    st = state_of(post)
    if st not in allowed:
        hint = {
            STATE_READY: "Draft sedang di tangan pimpinan dan terkunci. Pimpinan memakai leader_edit, atau return_to_admin untuk membukanya.",
            STATE_PUBLISHED: "Sudah tayang. Perubahan fakta lewat publish_correction (pimpinan).",
        }.get(st, "")
        raise WorkflowError(f"Tidak bisa {action}: status sekarang '{st}'. {hint}".strip(),
                            detail={"state": st, "allowed": list(allowed)})
    return st


def summarize_post(post: dict[str, Any]) -> dict[str, Any]:
    m = meta(post)
    return {"id": post.get("id"), "type": post.get("type"), "title": raw(post.get("title")),
            "status": post.get("status"), "state": state_of(post), "date": post.get("date"),
            "modified": post.get("modified"), "link": post.get("link"), "categories": post.get("categories"),
            "tags": post.get("tags"), "featured_media": post.get("featured_media"),
            "drafted_by": m.get("_wpmcp_drafted_by"), "submitted_at": m.get("_wpmcp_submitted_at")}


def append_meta_list(post: dict[str, Any], key: str, item: dict[str, Any], keep: int = 50) -> str:
    items = meta_json(post, key) + [item]
    return json.dumps(items[-keep:], ensure_ascii=False)


def directory_records(ctx: ToolContext, verified_only: bool = False) -> list[dict[str, Any]]:
    rows = ctx.state.query("SELECT kind, key, record_json, verified, source FROM directory")
    out = [{"kind": r["kind"], "key": r["key"], "record": json.loads(r["record_json"]),
            "verified": bool(r["verified"]), "source": r["source"]} for r in rows]
    return [r for r in out if r["verified"]] if verified_only else out


def directory_value(ctx: ToolContext, kind: str, key: str, default: str = "") -> str:
    row = ctx.state.one("SELECT record_json FROM directory WHERE kind=? AND key=? AND verified=1", (kind, key))
    if not row:
        return default
    return json.loads(row["record_json"]).get("nilai", default) or default


def media_resolver(ctx: ToolContext):
    cache: dict[int, dict[str, Any]] = {}

    def resolve(media_id: int) -> dict[str, Any]:
        if media_id not in cache:
            m = ctx.wp.get(f"/wp/v2/media/{media_id}", context="edit").data
            sizes = (m.get("media_details") or {}).get("sizes") or {}
            url = (sizes.get("large") or sizes.get("full") or {}).get("source_url") or m.get("source_url", "")
            cache[media_id] = {"url": url, "alt": m.get("alt_text", "")}
        return cache[media_id]

    return resolve


def now_id(ts: float | None = None) -> str:
    """'Senin, 12 Oktober 2026 pukul 14.05' (waktu server)."""
    d = datetime.fromtimestamp(ts or time.time())
    return f"{DAYS_ID[d.weekday()]}, {d.day} {MONTHS_ID[d.month - 1]} {d.year} pukul {d.hour:02d}.{d.minute:02d}"


def text_of(post: dict[str, Any]) -> str:
    return plain_text(raw(post.get("title")) + ". " + raw(post.get("content")))
