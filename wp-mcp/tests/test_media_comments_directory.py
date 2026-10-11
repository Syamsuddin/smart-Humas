from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image

from conftest import FILLED_DIRECTORY
from fake_wp import add_citizen_comment

ROOT = Path(__file__).resolve().parents[1]


def _jpeg_with_exif(w=2000, h=1500) -> bytes:
    img = Image.new("RGB", (w, h), (120, 160, 200))
    exif = Image.Exif()
    exif[0x010F] = "KameraHumas"          # Make
    exif[0x8825] = {2: (3.0, 14.0, 1.0)}  # GPSInfo (lokasi)
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif.tobytes())
    return buf.getvalue()


# --- media ------------------------------------------------------------------
def test_upload_featured_resizes_webp_and_strips_exif(env_dir):
    e = env_dir
    raw = _jpeg_with_exif()
    assert b"KameraHumas" in raw
    r = e.ok("operator-ai", "upload_media", alt_text="Peserta sosialisasi manajemen talenta di aula",
             data_base64=base64.b64encode(raw).decode(), role="featured", caption="Sosialisasi manajemen talenta.",
             credit="(Foto: BKPSDM Contoh)", title="sosialisasi talenta")
    assert (r["width"], r["height"]) == (1200, 675)
    stored = e.wp.media_bytes[r["id"]]
    img = Image.open(io.BytesIO(stored))
    assert img.format == "WEBP" and img.size == (1200, 675)
    assert b"KameraHumas" not in stored and not img.getexif()
    assert e.wp.media[r["id"]]["alt_text"].startswith("Peserta")
    assert e.wp.media[r["id"]]["caption"]["raw"].endswith("(Foto: BKPSDM Contoh)")
    assert r["filename"].endswith("-sosialisasi-talenta-01.webp")
    assert r["markdown"].startswith("![Peserta")


def test_upload_rejects_paths_outside_inbox(env_dir):
    r = env_dir.call("operator-ai", "upload_media", alt_text="x", local_path=str(env_dir.cfgdir / "secrets.env"))
    assert r["error"]["code"] == "INVALID_INPUT"
    p = env_dir.inbox / "a.jpg"
    p.write_bytes(_jpeg_with_exif(800, 600))
    r = env_dir.call("operator-ai", "upload_media", alt_text="Kegiatan rapat", local_path=str(p), role="gallery")
    assert r["ok"] and r["data"]["width"] == 800


def test_image_in_draft_becomes_block(env_dir):
    e = env_dir
    m = e.ok("operator-ai", "upload_media", alt_text="Suasana rapat", role="inline",
             data_base64=base64.b64encode(_jpeg_with_exif(1600, 900)).decode())
    d = e.ok("operator-ai", "create_draft", title="Rapat", content_markdown=f"Isi.\n\n{m['markdown']}",
             featured_media_id=m["id"])
    content = e.wp.posts[d["id"]]["content"]
    assert f'<!-- wp:image {{"id":{m["id"]}' in content and 'alt="Suasana rapat"' in content


# --- komentar ---------------------------------------------------------------
def test_comment_flow_masks_and_routes_approval(env_dir):
    e = env_dir
    d = e.ok("operator-ai", "create_draft", title="Layanan Cuti", content_markdown="Isi.")
    c1 = add_citizen_comment(e.wp, d["id"], "Bagaimana cara mengurus cuti? HP saya 081234567890", "warga@gmail.com")
    c2 = add_citizen_comment(e.wp, d["id"], "Pelayanan di loket sangat lambat, saya kecewa.")
    lst = e.ok("operator-ai", "list_comments")
    texts = {x["id"]: x for x in lst["items"]}
    assert "081234567890" not in texts[c1]["content"] and "disamarkan" in texts[c1]["content"]
    assert texts[c1]["author_ref"].startswith("h:") and "warga@gmail.com" not in str(lst)

    r1 = e.ok("operator-ai", "draft_reply", comment_id=c1, reply_class="pertanyaan_layanan",
              content="Terima kasih, Bapak/Ibu. Pengajuan cuti dapat dilakukan melalui aplikasi layanan kepegawaian.")
    r2 = e.ok("operator-ai", "draft_reply", comment_id=c2, reply_class="aduan",
              content="Terima kasih, Bapak/Ibu. Masukan ini kami teruskan ke unit terkait melalui kanal aduan resmi.")
    assert r2["approver"] == "pimpinan"
    # balasan yang sudah ada draftnya tidak muncul lagi sebagai 'belum dijawab'
    assert e.ok("operator-ai", "list_comments")["items"] == []

    # operator-ai tidak bisa mengirim; admin-web bisa kelas rutin, tidak bisa kelas aduan
    assert e.call("operator-ai", "send_reply", reply_id=r1["reply_id"])["error"]["code"] == "NOT_AUTHORIZED"
    p = e.call("admin1", "send_reply", reply_id=r1["reply_id"], approve_parent=True)
    assert e.confirm("admin1", p["pending_action"]["id"])["ok"]
    assert e.wp.comments[r1["reply_id"]]["status"] == "approved" and e.wp.comments[c1]["status"] == "approved"
    assert e.call("admin1", "send_reply", reply_id=r2["reply_id"])["error"]["code"] == "NOT_AUTHORIZED"
    p = e.call("pim1", "send_reply", reply_id=r2["reply_id"])
    assert e.confirm("pim1", p["pending_action"]["id"])["ok"]


# --- direktori --------------------------------------------------------------
def test_template_directory_is_incomplete(env):
    template = (ROOT / "wp_mcp" / "data" / "direktori-redaksi.md").read_text()
    r = env.ok("admin1", "directory_import", markdown=template)
    assert r["status"] == "draft" and "B.nama_resmi" in r["missing"]
    s = env.ok("operator-ai", "directory_status")
    assert s["missing"][0].startswith("B.")  # prioritas wawancara: B dulu


def test_filled_directory_complete_and_roundtrip(env_dir):
    e = env_dir
    s = e.ok("operator-ai", "directory_status")
    assert s["status"] == "lengkap-wajib", s
    md = e.ok("operator-ai", "directory_export")["markdown"]
    assert "| P01 | Drs. Budi Santoso, M.AP |" in md and "status: lengkap-wajib" in md
    # impor ulang hasil ekspor tetap lengkap
    e.ok("admin1", "directory_import", markdown=md, replace=True)
    assert e.ok("operator-ai", "directory_status")["status"] == "lengkap-wajib"


def test_directory_rejects_private_fields_and_retires_person(env_dir):
    e = env_dir
    r = e.call("admin1", "directory_set", kind="person", record={"kode": "P05", "nama_lengkap_bergelar": "Andi", "nip": "1978"})
    assert r["error"]["code"] == "INVALID_INPUT"
    e.ok("admin1", "directory_retire_person", kode="P03", sampai="2026-10-01", digantikan_oleh="P05")
    v = e.ok("operator-ai", "verify_names", text="Kepala Bidang PSDM, Rina Marlina, menjelaskan.")
    assert v["needs_review"][0]["type"] == "TITLE_MISMATCH"


def test_editorial_context_has_local_identity(env_dir):
    c = env_dir.ok("operator-ai", "get_editorial_context", purpose="berita")
    assert c["local"]["dateline"] == "KOTA BARU -" and c["local"]["kredit_foto"] == "(Foto: BKPSDM Contoh)"
    assert "Gaya Rumah" in c["style_guide"] and "approve_and_publish" not in c["your_tools"]
    assert c["directory_status"] == "lengkap-wajib"


def test_memory_lifecycle(env_dir):
    e = env_dir
    p = e.ok("operator-ai", "memory_propose", kind="style", key="sebutan-kepala",
             value={"benar": "Kepala BKPSDM", "salah": "Kaban"}, source="admin_edit_diff")
    assert p["status"] == "proposed"
    assert e.ok("operator-ai", "memory_lookup", kinds=["style"])["items"] == []  # usulan tidak dipakai
    assert e.call("operator-ai", "memory_confirm", memory_id=p["id"])["error"]["code"] == "NOT_AUTHORIZED"
    e.ok("admin1", "memory_confirm", memory_id=p["id"])
    assert e.ok("operator-ai", "memory_lookup", kinds=["style"])["items"][0]["value"]["benar"] == "Kepala BKPSDM"
    assert e.call("operator-ai", "memory_propose", kind="person", key="x", value={"a": 1})["error"]["code"] == "INVALID_INPUT"
    assert e.call("admin1", "memory_set", kind="reply", key="cuti",
                  value={"jawab": "hubungi 081234567890"})["error"]["code"] == "PII_BLOCKED"


def test_site_status_detects_adapters(env_dir):
    s = env_dir.ok("operator-ai", "site_status")
    assert s["cache"]["cache_adapters"] == ["litespeed-cache"]
    assert "wordfence" in s["rest"]["security_plugins"]
    assert s["rest"]["rest_ok"] and s["healthy"]
    assert s["theme"]["block_theme"] is False  # tema palsu tidak punya templates/index.html
