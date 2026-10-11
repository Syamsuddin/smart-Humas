"""Alur penuh tiga peran: operator-ai → admin-web → pimpinan, lewat HTTP ke WordPress palsu."""

from __future__ import annotations

BERITA = """KOTA BARU - Kepala BKD, Budi Santosa, membuka sosialisasi manajemen talenta di Aula Rakat Mupakat, Senin (12/10/2026).

Kegiatan diikuti 120 aparatur sipil negara dari 25 perangkat daerah.

Kepala Bidang PSDM, Rina Marlina, menjelaskan tahapan pemetaan talenta.

(BKPSDM Contoh)"""


def test_full_three_role_workflow(env_dir):
    e = env_dir
    # 1. operator-ai menyusun draft; ejaan salah dan singkatan terlarang dikoreksi otomatis
    d = e.ok("operator-ai", "create_draft", title="BKPSDM Sosialisasikan Manajemen Talenta",
             content_markdown=BERITA, categories=["Berita"], tags=["manajemen talenta"])
    pid = d["id"]
    post = e.wp.posts[pid]
    assert post["status"] == "draft"
    assert "Budi Santoso" in post["content"] and "Budi Santosa" not in post["content"]
    assert "Kepala BKPSDM" in post["content"] and "BKD" not in post["content"]
    assert "Aula Rakat Mufakat" in post["content"]
    assert post["meta"]["_wpmcp_state"] == "draft"
    assert d["blocking_markers"] == []

    # 2. operator-ai tidak bisa mengajukan atau menerbitkan
    assert e.call("operator-ai", "submit_to_leader", post_id=pid)["error"]["code"] == "NOT_AUTHORIZED"
    assert e.call("operator-ai", "approve_and_publish", post_id=pid)["error"]["code"] == "NOT_AUTHORIZED"

    # 3. admin-web meminta revisi; operator-ai mengeksekusi
    e.ok("admin1", "request_revision", post_id=pid, instruction="Lead terlalu panjang, singkat jadi 40 kata.")
    assert e.wp.posts[pid]["meta"]["_wpmcp_state"] == "revisi"
    e.ok("operator-ai", "update_draft", post_id=pid, content_markdown=BERITA.replace("Senin (12/10/2026)", "Senin"),
         revision_note="lead dipersingkat")

    # 4. admin-web mengajukan; pimpinan diberi tahu; draft terkunci untuk admin dan operator
    e.ok("admin1", "submit_to_leader", post_id=pid, note="Mohon arahan")
    assert e.wp.posts[pid]["status"] == "pending"
    assert any(a == "pim1" and "Menunggu persetujuan" in t for a, t in e.notifier.sent)
    locked = e.call("admin1", "update_draft", post_id=pid, title="ubah diam-diam")
    assert locked["error"]["code"] == "WORKFLOW"

    # 5. antrean pimpinan
    q = e.ok("pim1", "list_queue")
    assert [x["id"] for x in q["for_you"]] == [pid]

    # 6. pimpinan menyunting sedikit
    le = e.ok("pim1", "leader_edit", post_id=pid, instruction="ganti judul", title="BKPSDM Mulai Petakan Talenta ASN")
    assert le["readback"]["title_after"] == "BKPSDM Mulai Petakan Talenta ASN"
    assert e.wp.posts[pid]["title"] == "BKPSDM Mulai Petakan Talenta ASN"

    # 7. approve_and_publish → aksi tertunda dengan readback, belum tayang
    r = e.call("pim1", "approve_and_publish", post_id=pid)
    assert r["ok"] and r["data"] is None
    act = r["pending_action"]
    assert act["readback"]["title"] == "BKPSDM Mulai Petakan Talenta ASN"
    assert e.wp.posts[pid]["status"] == "pending"

    # 8. operator-ai tidak boleh mengonfirmasi; pimpinan mengonfirmasi → tayang
    assert e.confirm("operator-ai", act["id"])["error"]["code"] == "NOT_AUTHORIZED"
    done = e.confirm("pim1", act["id"])
    assert done["ok"], done
    assert e.wp.posts[pid]["status"] == "publish"
    assert e.wp.posts[pid]["meta"]["_wpmcp_approved_by"] == "pim1"
    # cache dibersihkan lewat adaptor litespeed yang terdeteksi
    log = e.cli_log.read_text()
    assert "cache flush" in log and "litespeed-purge all" in log
    # memori 'story' tercatat untuk berita berikutnya
    mem = e.ok("operator-ai", "memory_lookup", text="talenta", kinds=["story"])
    assert mem["items"] and mem["items"][0]["value"]["post_id"] == pid

    # 9. konfirmasi ulang aksi yang sama ditolak
    assert e.confirm("pim1", act["id"])["error"]["code"] == "EXPIRED"


def test_unverified_name_blocks_submit_and_publish(env_dir):
    e = env_dir
    d = e.ok("operator-ai", "create_draft", title="Camat Hadiri Rapat",
             content_markdown="KOTA BARU - Camat Kota Baru Utara, Siti Aminah, menghadiri rapat.")
    assert any("NAMA BELUM TERVERIFIKASI" in m for m in d["blocking_markers"])
    r = e.call("admin1", "submit_to_leader", post_id=d["id"])
    assert r["error"]["code"] == "NAMES_UNVERIFIED"


def test_publish_rejects_when_content_changed_after_pending(env_dir):
    e = env_dir
    d = e.ok("operator-ai", "create_draft", title="Pengumuman Seleksi", content_markdown="Isi pengumuman resmi.")
    e.ok("admin1", "submit_to_leader", post_id=d["id"])
    r = e.call("pim1", "approve_and_publish", post_id=d["id"])
    # seseorang mengubah isi lewat wp-admin setelah aksi dibuat
    e.wp.posts[d["id"]]["content"] = "isi berubah diam-diam"
    res = e.confirm("pim1", r["pending_action"]["id"])
    assert res["error"]["code"] == "CONTENT_CHANGED"
    assert e.wp.posts[d["id"]]["status"] == "pending"


def test_return_to_admin_unlocks(env_dir):
    e = env_dir
    d = e.ok("operator-ai", "create_draft", title="Rapat Koordinasi", content_markdown="Isi.")
    e.ok("admin1", "submit_to_leader", post_id=d["id"])
    e.ok("pim1", "return_to_admin", post_id=d["id"], note="Foto kurang layak")
    assert e.wp.posts[d["id"]]["meta"]["_wpmcp_state"] == "revisi"
    assert any(a == "admin1" and "Dikembalikan" in t for a, t in e.notifier.sent)
    e.ok("operator-ai", "update_draft", post_id=d["id"], title="Rapat Koordinasi Kepegawaian")


def test_delegation_lets_admin_publish(env_dir):
    e = env_dir
    d = e.ok("operator-ai", "create_draft", title="Pengumuman Libur", content_markdown="Isi pengumuman.", categories=["Pengumuman"])
    e.ok("admin1", "submit_to_leader", post_id=d["id"])
    # tanpa delegasi: ditolak
    assert e.call("admin1", "approve_and_publish", post_id=d["id"])["error"]["code"] == "NOT_AUTHORIZED"
    # pimpinan memberi delegasi (aksi tertunda, dikonfirmasi pimpinan)
    g = e.call("pim1", "grant_delegation", to_actor="admin1", days=3)
    assert e.confirm("pim1", g["pending_action"]["id"])["ok"]
    r = e.call("admin1", "approve_and_publish", post_id=d["id"])
    assert r["ok"] and r["pending_action"]["readback"]["delegation_id"]
    done = e.confirm("admin1", r["pending_action"]["id"])
    assert done["ok"], done
    assert e.wp.posts[d["id"]]["meta"]["_wpmcp_delegation_id"]
    # delegasi kedaluwarsa
    e.clock.advance(4 * 86400)
    d2 = e.ok("operator-ai", "create_draft", title="Pengumuman Lain", content_markdown="Isi.", categories=["Pengumuman"])
    e.ok("admin1", "submit_to_leader", post_id=d2["id"])
    assert e.call("admin1", "approve_and_publish", post_id=d2["id"])["error"]["code"] == "NOT_AUTHORIZED"


def test_correction_and_unpublish(env_dir):
    e = env_dir
    d = e.ok("operator-ai", "create_draft", title="Jadwal Seleksi", content_markdown="Seleksi dimulai 20 Oktober.")
    e.ok("admin1", "submit_to_leader", post_id=d["id"])
    e.confirm("pim1", e.call("pim1", "approve_and_publish", post_id=d["id"])["pending_action"]["id"])
    # admin-web tidak boleh memasang ralat
    assert e.call("admin1", "publish_correction", post_id=d["id"], correction_text="x")["error"]["code"] == "NOT_AUTHORIZED"
    c = e.call("pim1", "publish_correction", post_id=d["id"], correction_text="Seleksi dimulai 21 Oktober, bukan 20 Oktober.")
    assert e.confirm("pim1", c["pending_action"]["id"])["ok"]
    assert "Ralat," in e.wp.posts[d["id"]]["content"] and "21 Oktober" in e.wp.posts[d["id"]]["content"]
    u = e.call("pim1", "unpublish_post", post_id=d["id"], reason="Jadwal dibatalkan panitia.")
    assert e.confirm("pim1", u["pending_action"]["id"])["ok"]
    p = e.wp.posts[d["id"]]
    assert p["title"].startswith("[Dicabut]") and "Jadwal dibatalkan panitia." in p["content"]


def test_trash_needs_otp_and_technical_role(env_dir):
    e = env_dir
    d = e.ok("operator-ai", "create_draft", title="Draft Batal", content_markdown="Isi.")
    assert e.call("admin1", "trash_post", post_id=d["id"], reason="ganda")["error"]["code"] == "NOT_AUTHORIZED"
    r = e.call("tech1", "trash_post", post_id=d["id"], reason="ganda")
    act = r["pending_action"]
    assert act["needs_otp"]
    assert e.confirm("tech1", act["id"])["error"]["code"] == "NOT_AUTHORIZED"
    assert e.confirm("tech1", act["id"], otp="000000")["error"]["code"] == "NOT_AUTHORIZED"
    assert e.confirm("tech1", act["id"], otp=e.notifier.last_otp())["ok"]
    assert e.wp.posts[d["id"]]["status"] == "trash"


def test_pending_action_expires(env_dir):
    e = env_dir
    d = e.ok("operator-ai", "create_draft", title="Kedaluwarsa", content_markdown="Isi.")
    e.ok("admin1", "submit_to_leader", post_id=d["id"])
    r = e.call("pim1", "approve_and_publish", post_id=d["id"])
    e.clock.advance(16 * 60)
    assert e.confirm("pim1", r["pending_action"]["id"])["error"]["code"] == "EXPIRED"
