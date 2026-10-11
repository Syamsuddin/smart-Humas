"""Tool media: unggah foto yang sudah diolah (ukuran, WebP, tanpa EXIF), metadata, pemindaian dokumen identitas."""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path
from typing import Literal

from ..errors import InvalidInput, NotFound, PIIBlocked
from ..images import media_filename, process_image
from ..policy import HUMAN_ROLES, ToolContext, tool

Role = Literal["featured", "inline", "gallery", "social"]
MAX_UPLOAD_MB = 15
DEFAULT_INBOX = ["/var/lib/wp-mcp/inbox"]


def _read_source(ctx: ToolContext, local_path: str | None, data_base64: str | None) -> bytes:
    if data_base64:
        try:
            raw = base64.b64decode(data_base64.split(",", 1)[-1], validate=False)
        except Exception:
            raise InvalidInput("data_base64 tidak valid.") from None
    elif local_path:
        # Hanya dari folder kotak masuk: mencegah tool membaca berkas sembarang di server (mis. secrets.env).
        p = Path(local_path).resolve()
        inboxes = [Path(x).resolve() for x in (ctx.cfg.get("media.inbox_dirs") or DEFAULT_INBOX)]
        if not any(p.is_relative_to(i) for i in inboxes):
            raise InvalidInput(f"local_path harus berada di folder kotak masuk media: {[str(i) for i in inboxes]}. "
                               "Dari laptop, kirim gambar sebagai data_base64.")
        if not p.is_file():
            raise NotFound(f"Berkas {local_path} tidak ada.")
        raw = p.read_bytes()
    else:
        raise InvalidInput("Isi data_base64 atau local_path.")
    if len(raw) > MAX_UPLOAD_MB * 1024 * 1024:
        raise InvalidInput(f"Berkas melebihi {MAX_UPLOAD_MB} MB.")
    return raw


@tool("upload_media", level="1", pii_fields=("alt_text", "caption", "title"), group="media")
def upload_media(ctx: ToolContext, alt_text: str, data_base64: str | None = None, local_path: str | None = None,
                 role: Role = "inline", caption: str | None = None, credit: str | None = None,
                 title: str | None = None, post_id: int | None = None, index: int = 1,
                 confirm_public_pii: bool = False, idempotency_key: str | None = None) -> dict:
    """Unggah foto berita. WP-MCP mengubah ukuran sesuai peran (featured 1200×675 crop ke wajah; inline lebar 1024;
    gallery lebar 800; social 1080×1080), konversi WebP, membuang EXIF/lokasi, dan memindai dokumen identitas (OCR lokal).
    alt_text wajib (≤125 karakter, tanpa kata 'foto'/'gambar'). credit dari Direktori, mis. '(Foto: Humas Setda)'."""
    alt_text = alt_text.strip()
    if not alt_text:
        raise InvalidInput("alt_text wajib diisi.")
    if len(alt_text) > 125:
        ctx.warn("ALT_LONG", f"alt text {len(alt_text)} karakter; pedoman maksimal 125.")
    if alt_text.lower().startswith(("foto", "gambar")):
        ctx.warn("ALT_STYLE", "alt text sebaiknya langsung menggambarkan isi, tanpa awalan 'foto'/'gambar'.")
    raw = _read_source(ctx, local_path, data_base64)
    spec = ctx.cfg.get(f"media.{role}")
    if not spec:
        raise InvalidInput(f"Peran media '{role}' tidak dikonfigurasi.")
    processed = process_image(raw, role, spec)

    scan = None
    if ctx.cfg.get("privacy.ocr_media", True):
        with tempfile.NamedTemporaryFile(suffix=".webp") as tmp:
            tmp.write(processed.data)
            tmp.flush()
            scan = ctx.scanner.scan_image(tmp.name)
        if scan["suspicious"]:
            if confirm_public_pii and ctx.actor.role in HUMAN_ROLES:
                ctx.warn("ID_DOCUMENT_CONFIRMED", "Gambar terindikasi dokumen identitas; dikonfirmasi publik oleh manusia.")
            else:
                raise PIIBlocked("Gambar terindikasi memuat dokumen identitas atau data pribadi. Keputusan ada pada "
                                 "admin-web/pimpinan (confirm_public_pii=true).", detail=scan)

    name = media_filename(title or alt_text, index, processed.format)
    media = ctx.wp.upload(processed.data, name, f"image/{processed.format}").data
    full_caption = " ".join(x for x in [(caption or "").strip(), (credit or "").strip()] if x)
    meta_body = {"alt_text": alt_text, "title": title or alt_text[:80]}
    if full_caption:
        meta_body["caption"] = full_caption
    if post_id:
        meta_body["post"] = int(post_id)
    media = ctx.wp.post(f"/wp/v2/media/{media['id']}", meta_body).data
    return {"id": media["id"], "url": media.get("source_url"), "filename": name, "role": role,
            "width": processed.width, "height": processed.height, "kb": round(processed.bytes_size / 1024, 1),
            "quality": processed.quality, "crop": processed.crop_strategy, "exif_removed": True,
            "markdown": f'![{alt_text}](wpmedia:{media["id"]} "{full_caption}")',
            "ocr": {"checked": bool(scan and scan["ocr_available"]), "suspicious": bool(scan and scan["suspicious"])}}


@tool("list_media", level="0", group="media")
def list_media(ctx: ToolContext, missing_alt: bool = False, since: str | None = None, limit: int = 20,
               cursor: str | None = None) -> dict:
    """Daftar media gambar. missing_alt=true untuk mencari gambar tanpa alt text (audit aksesibilitas)."""
    page = int(cursor or 1)
    resp = ctx.wp.get("/wp/v2/media", context="edit", media_type="image", after=since,
                      per_page=max(1, min(int(limit), 100)), page=page, orderby="date", order="desc")
    items = [{"id": m["id"], "title": (m.get("title") or {}).get("raw"), "alt_text": m.get("alt_text", ""),
              "url": m.get("source_url"), "date": m.get("date"), "attached_to": m.get("post")} for m in resp.data or []]
    if missing_alt:
        items = [i for i in items if not (i["alt_text"] or "").strip()]
    more = resp.total_pages is not None and page < resp.total_pages
    return {"items": items, "next_cursor": str(page + 1) if more else None}


@tool("update_media_meta", level="1", pii_fields=("alt_text", "caption", "title"), group="media")
def update_media_meta(ctx: ToolContext, media_id: int, alt_text: str | None = None, caption: str | None = None,
                      title: str | None = None, confirm_public_pii: bool = False) -> dict:
    """Ubah alt text, keterangan, atau judul media."""
    body = {k: v for k, v in {"alt_text": alt_text, "caption": caption, "title": title}.items() if v is not None}
    if not body:
        raise InvalidInput("Tidak ada yang diubah.")
    m = ctx.wp.post(f"/wp/v2/media/{int(media_id)}", body).data
    return {"id": m["id"], "alt_text": m.get("alt_text"), "updated": sorted(body)}


@tool("scan_media_pii", level="0", group="media")
def scan_media_pii(ctx: ToolContext, media_id: int) -> dict:
    """Pindai media yang sudah ada untuk dokumen identitas (OCR lokal; gambar tidak dikirim keluar server)."""
    m = ctx.wp.get(f"/wp/v2/media/{int(media_id)}", context="edit").data
    url = m.get("source_url", "")
    site = ctx.cfg.get("site.url", "").rstrip("/")
    marker = "/wp-content/uploads/"
    if marker not in url:
        raise NotFound("Lokasi berkas media tidak dikenali.")
    uploads = (Path(ctx.cfg.get("site.wp_path")) / "wp-content" / "uploads").resolve()
    local = (uploads / url.split(marker, 1)[1].split("?")[0]).resolve()
    if not local.is_relative_to(uploads):
        raise InvalidInput("Lokasi media di luar folder uploads.")
    if not local.is_file():
        raise NotFound(f"Berkas lokal tidak ditemukan ({local}).", detail={"site": site})
    return {"id": m["id"], **ctx.scanner.scan_image(local)}
