"""Tool konten dan alur persetujuan berjenjang: operator-ai → admin-web → pimpinan."""

from __future__ import annotations

import difflib
import json
from typing import Any

from ..adapters import cache as cache_adapter
from ..errors import InvalidInput, NamesUnverified, NotAuthorized, WorkflowError, WPMCPError
from ..markdown_blocks import markdown_to_blocks, plain_text
from ..names import blocking_markers, check_names
from ..policy import HUMAN_ROLES, ToolContext, tool
from . import _common as c
from .delegation import active_delegation_for
from .memory import add_story_memory


# ---------------------------------------------------------------------------
# pembantu
# ---------------------------------------------------------------------------
def _ensure_terms(ctx: ToolContext, taxonomy: str, values: list[Any] | None) -> list[int] | None:
    """Terima ID atau nama. Nama tag yang belum ada dibuat; nama kategori yang belum ada ditolak."""
    if values is None:
        return None
    path = "/wp/v2/categories" if taxonomy == "category" else "/wp/v2/tags"
    ids: list[int] = []
    for v in values:
        if isinstance(v, int) or (isinstance(v, str) and v.isdigit()):
            ids.append(int(v))
            continue
        name = str(v).strip()
        if not name:
            continue
        found = ctx.wp.get(path, search=name, per_page=20).data or []
        match = next((t for t in found if t.get("name", "").lower() == name.lower()), None)
        if match:
            ids.append(match["id"])
        elif taxonomy == "category":
            raise InvalidInput(f"Kategori '{name}' tidak ada. Kategori tidak dibuat otomatis; pilih dari list_terms.",
                               detail={"available": [t.get("name") for t in found]})
        else:
            ids.append(ctx.wp.post(path, {"name": name}).data["id"])
    return ids


def _prepare_content(ctx: ToolContext, markdown: str, allow_html: bool) -> dict[str, Any]:
    limit = int(ctx.cfg.get("limits.content_max_kb", 200)) * 1024
    if len(markdown.encode()) > limit:
        raise InvalidInput(f"content_markdown melebihi {limit // 1024} KB.")
    if allow_html and ctx.actor.role not in HUMAN_ROLES:
        raise NotAuthorized("allow_html hanya boleh dari admin-web atau pimpinan.")
    check = check_names(markdown, c.directory_records(ctx, verified_only=True))
    conv = markdown_to_blocks(check.text, c.media_resolver(ctx), allow_html=allow_html)
    for w in conv.warnings:
        ctx.warn("CONTENT", w)
    for f in check.findings:
        if f["type"].endswith("_FIXED"):
            ctx.warn(f["type"], f"{f['from']} → {f['to']}")
    return {"content": conv.content, "name_check": check.as_dict() | {"text": None},
            "word_count": conv.word_count, "media_ids": conv.media_ids,
            "markers": blocking_markers(check.text)}


def _title_check(ctx: ToolContext, title: str) -> str:
    check = check_names(title, c.directory_records(ctx, verified_only=True))
    if len(check.text) > 70:
        ctx.warn("TITLE_LONG", f"Judul {len(check.text)} karakter; pedoman maksimal 70.")
    if "!" in check.text:
        ctx.warn("TITLE_STYLE", "Judul memakai tanda seru; pedoman melarangnya.")
    return check.text


def _diff_summary(before: str, after: str, limit: int = 12) -> list[str]:
    a = plain_text(before).split(". ")
    b = plain_text(after).split(". ")
    lines = [ln for ln in difflib.unified_diff(a, b, lineterm="", n=0) if ln[:1] in "+-" and ln[:3] not in ("+++", "---")]
    return lines[:limit]


# ---------------------------------------------------------------------------
# baca
# ---------------------------------------------------------------------------
@tool("list_posts", level="0", group="content")
def list_posts(ctx: ToolContext, state: str | None = None, search: str | None = None, category: int | None = None,
               since: str | None = None, limit: int = 20, cursor: str | None = None, type: c.PostType = "post") -> dict:
    """Daftar berita/halaman. state: draft | revisi | siap_tayang | published (kosong = semua).
    since format ISO (2026-10-01T00:00:00). cursor = nilai 'next_cursor' dari hasil sebelumnya."""
    wp_status = {"draft": "draft", "revisi": "draft", "siap_tayang": "pending", "published": "publish,future"}.get(
        state or "", "draft,pending,publish,future")
    page = int(cursor or 1)
    resp = ctx.wp.get(c.endpoint(type), context="edit", status=wp_status, search=search, categories=category,
                      after=since, per_page=max(1, min(int(limit), 100)), page=page, orderby="modified", order="desc")
    items = [c.summarize_post(p) for p in (resp.data or [])]
    if state:
        items = [i for i in items if i["state"] == state]
    more = resp.total_pages is not None and page < resp.total_pages
    return {"items": items, "next_cursor": str(page + 1) if more else None, "total": resp.total}


@tool("get_post", level="0", group="content")
def get_post(ctx: ToolContext, post_id: int, type: c.PostType = "post", include_html: bool = False) -> dict:
    """Baca satu berita/halaman lengkap: judul, isi (teks polos; HTML blok bila include_html), meta alur kerja,
    tanda yang belum beres, dan hash konten."""
    post = c.fetch_post(ctx, post_id, type)
    html = c.raw(post.get("content"))
    text = plain_text(html)
    out = c.summarize_post(post) | {
        "excerpt": c.raw(post.get("excerpt")), "text": text, "word_count": len(text.split()),
        "blocking_markers": blocking_markers(text + " " + c.raw(post.get("title"))),
        "revision_requests": c.meta_json(post, "_wpmcp_revision_requests"),
        "leader_edits": c.meta_json(post, "_wpmcp_leader_edits"),
        "corrections": c.meta_json(post, "_wpmcp_corrections"),
        "reviewer_note": c.meta(post).get("_wpmcp_reviewer_note"), "content_hash": c.post_hash(post),
        "preview_link": f"{post.get('link')}&preview=true" if "?" in (post.get("link") or "") else f"{post.get('link')}?preview=true",
    }
    if include_html:
        out["html"] = html
    return out


@tool("list_queue", level="0", group="workflow")
def list_queue(ctx: ToolContext, type: c.PostType = "post") -> dict:
    """Antrean alur kerja: draft, revisi, dan siap_tayang. Untuk pimpinan, 'menunggu_anda' = siap_tayang,
    ditandai terlambat bila melewati limits.leader_reminder_hours sejak diajukan."""
    resp = ctx.wp.get(c.endpoint(type), context="edit", status="draft,pending", per_page=100, orderby="modified", order="desc")
    hours = float(ctx.cfg.get("limits.leader_reminder_hours", 24))
    queue: dict[str, list] = {c.STATE_DRAFT: [], c.STATE_REVISI: [], c.STATE_READY: []}
    for p in resp.data or []:
        s = c.summarize_post(p)
        if s["state"] == c.STATE_READY:
            sub = c.meta(p).get("_wpmcp_submitted_at")
            try:
                waited = (ctx.now - float(sub)) / 3600 if sub else None
            except ValueError:
                waited = None
            s["waiting_hours"] = round(waited, 1) if waited is not None else None
            s["overdue"] = bool(waited and waited > hours)
        queue.setdefault(s["state"], []).append(s)
    mine = queue[c.STATE_READY] if ctx.actor.role == "pimpinan" else queue[c.STATE_DRAFT] + queue[c.STATE_REVISI]
    return {"for_you": mine, "counts": {k: len(v) for k, v in queue.items()}, "queue": queue}


# ---------------------------------------------------------------------------
# tulis draft
# ---------------------------------------------------------------------------
@tool("create_draft", level="1", pii_fields=("title", "content_markdown", "excerpt", "tags", "source_note"), group="content")
def create_draft(ctx: ToolContext, title: str, content_markdown: str, type: c.PostType = "post",
                 categories: list[int | str] | None = None, tags: list[int | str] | None = None,
                 excerpt: str | None = None, featured_media_id: int | None = None, source_note: str | None = None,
                 allow_html: bool = False, idempotency_key: str | None = None,
                 confirm_public_pii: bool = False) -> dict:
    """Buat draft berita/halaman dari Markdown. Status selalu 'draft' apa pun yang diminta.
    Nama pejabat/OPD/tempat diperiksa terhadap Direktori: ejaan salah diperbaiki otomatis, nama tak dikenal ditandai.
    Gambar: ![alt](wpmedia:ID "keterangan"); galeri: ```gallery\\nID, ID\\n```. Kategori harus sudah ada."""
    prepared = _prepare_content(ctx, content_markdown, allow_html)
    body: dict[str, Any] = {
        "title": _title_check(ctx, title), "content": prepared["content"], "status": "draft",
        "meta": {"_wpmcp_state": c.STATE_DRAFT, "_wpmcp_drafted_by": f"operator-ai via {ctx.actor.id}"},
    }
    if source_note:
        body["meta"]["_wpmcp_source_note"] = source_note[:500]
    if excerpt:
        body["excerpt"] = excerpt
    if type == "post":
        cats = _ensure_terms(ctx, "category", categories)
        if cats is not None:
            body["categories"] = cats
        tg = _ensure_terms(ctx, "tag", tags)
        if tg is not None:
            body["tags"] = tg
    if featured_media_id:
        body["featured_media"] = int(featured_media_id)
    elif type == "post":
        ctx.warn("NO_FEATURED_IMAGE", "Belum ada foto utama (featured_media_id).")
    post = ctx.wp.post(c.endpoint(type), body).data
    return {"id": post["id"], "status": post.get("status"), "state": c.STATE_DRAFT, "link": post.get("link"),
            "edit_link": f"{ctx.cfg.get('site.url').rstrip('/')}/wp-admin/post.php?post={post['id']}&action=edit",
            "word_count": prepared["word_count"], "name_check": prepared["name_check"],
            "blocking_markers": prepared["markers"]}


@tool("update_draft", level="1", pii_fields=("title", "content_markdown", "excerpt", "tags", "revision_note"), group="content")
def update_draft(ctx: ToolContext, post_id: int, type: c.PostType = "post", title: str | None = None,
                 content_markdown: str | None = None, excerpt: str | None = None,
                 categories: list[int | str] | None = None, tags: list[int | str] | None = None,
                 featured_media_id: int | None = None, revision_note: str | None = None,
                 allow_html: bool = False, confirm_public_pii: bool = False) -> dict:
    """Ubah draft yang berstatus draft/revisi. Draft siap_tayang terkunci (pimpinan memakai leader_edit)."""
    post = c.fetch_post(ctx, post_id, type)
    c.require_state(post, c.EDITABLE_STATES, "mengubah draft")
    body: dict[str, Any] = {"meta": {}}
    out: dict[str, Any] = {}
    if title is not None:
        body["title"] = _title_check(ctx, title)
    if content_markdown is not None:
        prepared = _prepare_content(ctx, content_markdown, allow_html)
        body["content"] = prepared["content"]
        out |= {"word_count": prepared["word_count"], "name_check": prepared["name_check"],
                "blocking_markers": prepared["markers"]}
    if excerpt is not None:
        body["excerpt"] = excerpt
    if type == "post":
        if categories is not None:
            body["categories"] = _ensure_terms(ctx, "category", categories)
        if tags is not None:
            body["tags"] = _ensure_terms(ctx, "tag", tags)
    if featured_media_id is not None:
        body["featured_media"] = int(featured_media_id)
    body["meta"]["_wpmcp_revised_by"] = c.append_meta_list(post, "_wpmcp_revised_by", {
        "actor": ctx.actor.id, "role": ctx.actor.role, "at": int(ctx.now), "note": (revision_note or "")[:300]})
    updated = ctx.wp.post(f"{c.endpoint(type)}/{int(post_id)}", body).data
    return out | {"id": updated["id"], "state": c.state_of(updated), "revisions": len(c.meta_json(updated, "_wpmcp_revised_by"))}


# ---------------------------------------------------------------------------
# alur persetujuan
# ---------------------------------------------------------------------------
@tool("request_revision", level="1", roles=HUMAN_ROLES, pii_fields=("instruction",), group="workflow")
def request_revision(ctx: ToolContext, post_id: int, instruction: str, type: c.PostType = "post") -> dict:
    """Admin-web (atau pimpinan) memberi perintah perbaikan pada draft. Status menjadi 'revisi'.
    operator-ai lalu mengeksekusinya dengan update_draft."""
    post = c.fetch_post(ctx, post_id, type)
    c.require_state(post, c.EDITABLE_STATES, "meminta revisi")
    body = {"meta": {"_wpmcp_state": c.STATE_REVISI, "_wpmcp_revision_requests": c.append_meta_list(
        post, "_wpmcp_revision_requests", {"by": ctx.actor.id, "role": ctx.actor.role, "at": int(ctx.now), "instruction": instruction[:1000]})}}
    ctx.wp.post(f"{c.endpoint(type)}/{int(post_id)}", body)
    return {"id": int(post_id), "state": c.STATE_REVISI, "instruction": instruction,
            "next": "operator-ai menjalankan instruksi ini dengan update_draft, lalu admin-web memeriksa hasilnya."}


def _describe_submit(ctx: ToolContext, args: dict) -> dict:
    post = c.fetch_post(ctx, args["post_id"], args.get("type", "post"))
    text = plain_text(c.raw(post.get("content")))
    return {"summary": f"Ajukan ke pimpinan #{post['id']} \"{c.raw(post.get('title'))[:90]}\"",
            "impact": ["draft terkunci untuk admin", "pimpinan diberi tahu"], "content_hash": c.post_hash(post),
            "readback": {"title": c.raw(post.get("title")), "word_count": len(text.split()), "excerpt": text[:600],
                         "note": args.get("note")}}


@tool("submit_to_leader", level="2a", roles=("admin-web",), pii_fields=("note",), describe_pending=_describe_submit, group="workflow")
def submit_to_leader(ctx: ToolContext, post_id: int, note: str | None = None, type: c.PostType = "post") -> dict:
    """Admin-web mengajukan draft ke pimpinan. Status menjadi 'siap_tayang' dan draft terkunci untuk admin.
    Ditolak bila masih ada tanda [NAMA BELUM TERVERIFIKASI], [BELUM ADA DI BAHAN], [KUTIPAN: ...]."""
    post = c.fetch_post(ctx, post_id, type)
    c.require_state(post, c.EDITABLE_STATES, "mengajukan ke pimpinan")
    markers = blocking_markers(c.text_of(post))
    if markers:
        raise NamesUnverified("Masih ada tanda yang harus diselesaikan sebelum diajukan: " + ", ".join(markers),
                              detail={"markers": markers})
    if type == "post" and not post.get("featured_media"):
        ctx.warn("NO_FEATURED_IMAGE", "Diajukan tanpa foto utama.")
    body = {"status": "pending", "meta": {"_wpmcp_state": c.STATE_READY, "_wpmcp_submitted_by": ctx.actor.id,
                                          "_wpmcp_submitted_at": str(int(ctx.now)), "_wpmcp_reviewer_note": (note or "")[:500]}}
    ctx.wp.post(f"{c.endpoint(type)}/{int(post_id)}", body)
    sent = ctx.notify_role("pimpinan", f"[Humas] Menunggu persetujuan Bapak/Ibu: #{post_id} \"{c.raw(post.get('title'))[:80]}\""
                                       + (f" — catatan: {note[:120]}" if note else ""))
    return {"id": int(post_id), "state": c.STATE_READY, "leaders_notified": sent}


@tool("leader_edit", level="1", roles=("pimpinan",), pii_fields=("title", "content_markdown", "excerpt"), group="workflow")
def leader_edit(ctx: ToolContext, post_id: int, instruction: str, title: str | None = None,
                content_markdown: str | None = None, excerpt: str | None = None, type: c.PostType = "post",
                confirm_public_pii: bool = False) -> dict:
    """Suntingan pimpinan pada draft siap_tayang (yang terkunci untuk admin). Dieksekusi operator-ai atas perintah
    pimpinan; hasilnya dikembalikan sebagai perbandingan sebelum-sesudah dan dicatat di _wpmcp_leader_edits."""
    post = c.fetch_post(ctx, post_id, type)
    c.require_state(post, (c.STATE_READY,), "menyunting sebagai pimpinan")
    body: dict[str, Any] = {"meta": {}}
    before_title, before_html = c.raw(post.get("title")), c.raw(post.get("content"))
    if title is not None:
        body["title"] = _title_check(ctx, title)
    prepared = None
    if content_markdown is not None:
        prepared = _prepare_content(ctx, content_markdown, False)
        body["content"] = prepared["content"]
    if excerpt is not None:
        body["excerpt"] = excerpt
    diff = _diff_summary(before_html, body.get("content", before_html))
    record = {"at": int(ctx.now), "by": ctx.actor.id, "instruction": instruction[:500],
              "title_before": before_title if title is not None else None,
              "title_after": body.get("title"), "changes": diff}
    body["meta"]["_wpmcp_leader_edits"] = c.append_meta_list(post, "_wpmcp_leader_edits", record)
    ctx.wp.post(f"{c.endpoint(type)}/{int(post_id)}", body)
    return {"id": int(post_id), "state": c.STATE_READY, "readback": {
        "title_before": before_title, "title_after": body.get("title", before_title), "changes": diff},
        "blocking_markers": prepared["markers"] if prepared else [],
        "next": "Bacakan perubahan ke pimpinan, lalu approve_and_publish bila disetujui."}


@tool("return_to_admin", level="2a", roles=("pimpinan",), pii_fields=("note",), group="workflow")
def return_to_admin(ctx: ToolContext, post_id: int, note: str, type: c.PostType = "post") -> dict:
    """Pimpinan mengembalikan draft siap_tayang ke admin-web dengan catatan. Kunci dibuka, status 'revisi'."""
    post = c.fetch_post(ctx, post_id, type)
    c.require_state(post, (c.STATE_READY,), "mengembalikan ke admin")
    body = {"status": "draft", "meta": {"_wpmcp_state": c.STATE_REVISI, "_wpmcp_revision_requests": c.append_meta_list(
        post, "_wpmcp_revision_requests", {"by": ctx.actor.id, "role": "pimpinan", "at": int(ctx.now), "instruction": note[:1000]})}}
    ctx.wp.post(f"{c.endpoint(type)}/{int(post_id)}", body)
    sent = ctx.notify_role("admin-web", f"[Humas] Dikembalikan pimpinan: #{post_id} \"{c.raw(post.get('title'))[:80]}\" — {note[:160]}")
    return {"id": int(post_id), "state": c.STATE_REVISI, "note": note, "admins_notified": sent}


def _authorize_publish(ctx: ToolContext, args: dict) -> None:
    if ctx.actor.role == "pimpinan":
        return
    post = c.fetch_post(ctx, args["post_id"], args.get("type", "post"))
    deleg = active_delegation_for(ctx, ctx.actor.id, post.get("categories") or [])
    if not deleg:
        raise NotAuthorized("Admin-web hanya bisa menerbitkan dengan delegasi aktif dari pimpinan untuk kategori ini.",
                            detail={"hint": "Pimpinan dapat memberi delegasi dengan grant_delegation."})
    args["_delegation_id"] = deleg["id"]


def _describe_publish(ctx: ToolContext, args: dict) -> dict:
    post_type = args.get("type", "post")
    post = c.fetch_post(ctx, args["post_id"], post_type)
    if ctx.cfg.get("workflow.require_review_before_publish", True):
        c.require_state(post, (c.STATE_READY,), "menerbitkan")
    markers = blocking_markers(c.text_of(post))
    if markers:
        raise NamesUnverified("Tidak bisa terbit: masih ada tanda " + ", ".join(markers), detail={"markers": markers})
    cat_names = []
    for cid in post.get("categories") or []:
        try:
            cat_names.append(ctx.wp.get(f"/wp/v2/categories/{cid}").data.get("name"))
        except WPMCPError:
            cat_names.append(str(cid))
    text = plain_text(c.raw(post.get("content")))
    edits = c.meta_json(post, "_wpmcp_leader_edits")
    readback = {"title": c.raw(post.get("title")), "categories": cat_names, "word_count": len(text.split()),
                "body_excerpt": text[:700],
                "leader_changes": [ch for e in edits[-3:] for ch in (e.get("changes") or [])][:15],
                "images": c.raw(post.get("content")).count("<!-- wp:image"),
                "featured_image": bool(post.get("featured_media")), "leader_edits": len(edits),
                "name_check": "bersih", "delegation_id": args.get("_delegation_id")}
    when = f" dijadwalkan {args['schedule_at']}" if args.get("schedule_at") else ""
    return {"summary": f"Terbitkan #{post['id']} \"{readback['title'][:90]}\"{when}",
            "impact": ["tampil di situs publik", "masuk RSS dan beranda", "cache situs dibersihkan"],
            "content_hash": c.post_hash(post), "target_ref": f"{post_type}:{post['id']}", "readback": readback}


@tool("approve_and_publish", level="2b", roles=HUMAN_ROLES, authorize=_authorize_publish,
      describe_pending=_describe_publish, group="workflow")
def approve_and_publish(ctx: ToolContext, post_id: int, type: c.PostType = "post", schedule_at: str | None = None,
                        _delegation_id: int | None = None) -> dict:
    """Pimpinan menyetujui dan menerbitkan draft siap_tayang (admin-web hanya dengan delegasi aktif).
    Selalu lewat aksi tertunda: ringkasan dibacakan ulang, lalu confirm_action. schedule_at ISO untuk terbit terjadwal."""
    desc = _describe_publish(ctx, {"post_id": post_id, "type": type, "schedule_at": schedule_at})
    post = c.fetch_post(ctx, post_id, type)
    body: dict[str, Any] = {"status": "future" if schedule_at else "publish",
                            "meta": {"_wpmcp_state": c.STATE_PUBLISHED, "_wpmcp_approved_by": ctx.actor.id,
                                     "_wpmcp_published_by": ctx.actor.id}}
    if schedule_at:
        body["date"] = schedule_at
    if _delegation_id:
        body["meta"]["_wpmcp_delegation_id"] = str(_delegation_id)
    published = ctx.wp.post(f"{c.endpoint(type)}/{int(post_id)}", body).data
    cache = None
    if ctx.cli is not None:
        try:
            cache = cache_adapter.purge_all(ctx.cli)
        except WPMCPError as exc:
            ctx.warn("CACHE", f"Cache tidak dibersihkan: {exc.message}")
    try:
        add_story_memory(ctx, published, c.text_of(post))
    except WPMCPError:
        pass
    return {"id": published["id"], "status": published.get("status"), "link": published.get("link"),
            "approved_by": ctx.actor.id, "delegation_id": _delegation_id, "readback": desc["readback"], "cache": cache}


def _describe_correction(ctx: ToolContext, args: dict) -> dict:
    post = c.fetch_post(ctx, args["post_id"], args.get("type", "post"))
    c.require_state(post, (c.STATE_PUBLISHED,), "memasang ralat")
    return {"summary": f"Ralat pada #{post['id']} \"{c.raw(post.get('title'))[:80]}\": {args['correction_text'][:140]}",
            "impact": ["kotak ralat bertanggal tampil di akhir berita", "cache dibersihkan"],
            "content_hash": c.post_hash(post), "target_ref": f"{args.get('type', 'post')}:{post['id']}"}


@tool("publish_correction", level="2b", roles=("pimpinan",), describe_pending=_describe_correction,
      pii_fields=("correction_text",), group="workflow")
def publish_correction(ctx: ToolContext, post_id: int, correction_text: str, type: c.PostType = "post") -> dict:
    """Ralat terbuka pada berita yang sudah tayang: menambah kotak 'Ralat, [tanggal jam]: ...' di akhir berita
    (praktik Pedoman Pemberitaan Media Siber). Tidak menghapus diam-diam."""
    import html as _h
    post = c.fetch_post(ctx, post_id, type)
    stamp = c.now_id(ctx.now)
    block = ('<!-- wp:paragraph {"className":"wpmcp-ralat"} -->\n<p class="wpmcp-ralat"><strong>Ralat, '
             f"{_h.escape(stamp)}:</strong> {_h.escape(correction_text)}</p>\n<!-- /wp:paragraph -->")
    body = {"content": c.raw(post.get("content")).rstrip() + "\n\n" + block,
            "meta": {"_wpmcp_corrections": c.append_meta_list(post, "_wpmcp_corrections",
                                                              {"at": int(ctx.now), "by": ctx.actor.id, "text": correction_text[:1000]})}}
    ctx.wp.post(f"{c.endpoint(type)}/{int(post_id)}", body)
    if ctx.cli is not None:
        try:
            cache_adapter.purge_all(ctx.cli)
        except WPMCPError as exc:
            ctx.warn("CACHE", exc.message)
    return {"id": int(post_id), "correction": correction_text, "stamped": stamp}


def _describe_unpublish(ctx: ToolContext, args: dict) -> dict:
    post = c.fetch_post(ctx, args["post_id"], args.get("type", "post"))
    c.require_state(post, (c.STATE_PUBLISHED,), "mencabut")
    return {"summary": f"Cabut #{post['id']} \"{c.raw(post.get('title'))[:80]}\" — alasan: {args['reason'][:140]}",
            "impact": ["isi diganti pemberitahuan pencabutan beralasan", "URL lama tetap hidup", "isi asli tersimpan di revisi WordPress"],
            "content_hash": c.post_hash(post), "target_ref": f"{args.get('type', 'post')}:{post['id']}"}


@tool("unpublish_post", level="2b", roles=("pimpinan",), describe_pending=_describe_unpublish,
      pii_fields=("reason",), group="workflow")
def unpublish_post(ctx: ToolContext, post_id: int, reason: str, type: c.PostType = "post") -> dict:
    """Mencabut berita yang sudah tayang dengan alasan yang diumumkan di URL lama (bukan menghapus diam-diam).
    Isi asli tetap tersimpan sebagai revisi WordPress."""
    import html as _h
    post = c.fetch_post(ctx, post_id, type)
    title = c.raw(post.get("title"))
    notice = ('<!-- wp:paragraph {"className":"wpmcp-dicabut"} -->\n<p class="wpmcp-dicabut"><strong>Berita ini dicabut pada '
              f"{_h.escape(c.now_id(ctx.now))}.</strong> Alasan: {_h.escape(reason)}</p>\n<!-- /wp:paragraph -->")
    body = {"title": title if title.startswith("[Dicabut]") else f"[Dicabut] {title}", "content": notice,
            "meta": {"_wpmcp_withdrawn": json.dumps({"at": int(ctx.now), "by": ctx.actor.id, "reason": reason[:1000]}, ensure_ascii=False)}}
    ctx.wp.post(f"{c.endpoint(type)}/{int(post_id)}", body)
    if ctx.cli is not None:
        try:
            cache_adapter.purge_all(ctx.cli)
        except WPMCPError as exc:
            ctx.warn("CACHE", exc.message)
    return {"id": int(post_id), "withdrawn": True, "reason": reason}


def _describe_trash(ctx: ToolContext, args: dict) -> dict:
    post = c.fetch_post(ctx, args["post_id"], args.get("type", "post"))
    if c.state_of(post) == c.STATE_PUBLISHED:
        raise WorkflowError("Berita yang sudah tayang dicabut dengan unpublish_post (beralasan), bukan dibuang.")
    return {"summary": f"Pindahkan ke sampah #{post['id']} \"{c.raw(post.get('title'))[:80]}\" — {args['reason'][:120]}",
            "impact": ["draft hilang dari antrean", "bisa dipulihkan dari Sampah wp-admin selama 30 hari"],
            "content_hash": c.post_hash(post), "target_ref": f"{args.get('type', 'post')}:{post['id']}"}


@tool("trash_post", level="3", describe_pending=_describe_trash, group="workflow")
def trash_post(ctx: ToolContext, post_id: int, reason: str, type: c.PostType = "post") -> dict:
    """Buang draft yang tidak jadi ke Sampah WordPress (level 3: kode OTP). Berita tayang tidak bisa dibuang."""
    ctx.wp.delete(f"{c.endpoint(type)}/{int(post_id)}")
    return {"id": int(post_id), "trashed": True, "reason": reason}
