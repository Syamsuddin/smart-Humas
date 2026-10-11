"""Regresi untuk temuan tinjauan keamanan independen.

Inti: di pintu model (Claude Code), sesi memakai kunci SSH manusia tetapi yang menekan tombol adalah model.
Aksi ≥2a dari pintu ini hanya sah dengan persetujuan di luar percakapan (kode Telegram atau wp-admin).
"""

from __future__ import annotations

import json

from fake_wp import add_citizen_comment, decide

CC = "claude_code"


def _ready_post(e, title="Berita Uji"):
    d = e.ok("operator-ai", "create_draft", title=title, content_markdown="Isi berita resmi.", categories=["Berita"])
    e.ok("admin1", "submit_to_leader", post_id=d["id"])  # pintu manusia
    return d["id"]


# --- temuan kritis: konfirmasi dari percakapan yang sama ---------------------
def test_model_cannot_self_confirm_publish(env_dir):
    e = env_dir
    pid = _ready_post(e)
    r = e.call("pim1", "approve_and_publish", door=CC, post_id=pid)
    act = r["pending_action"]
    assert set(act["approval_channels"]) == {"otp", "wp_admin"}
    # model mencoba mengonfirmasi sendiri tanpa kode: ditolak, tidak tayang
    res = e.confirm("pim1", act["id"], door=CC)
    assert res["error"]["code"] == "NOT_AUTHORIZED"
    assert e.wp.posts[pid]["status"] == "pending"
    # manusia membaca kode di Telegram dan mengetiknya
    res = e.confirm("pim1", act["id"], otp=e.notifier.last_otp(), door=CC)
    assert res["ok"], res
    assert e.wp.posts[pid]["status"] == "publish"


def test_submit_from_model_door_needs_external_approval(env_dir):
    e = env_dir
    d = e.ok("operator-ai", "create_draft", title="Draft", content_markdown="Isi.")
    r = e.call("admin1", "submit_to_leader", door=CC, post_id=d["id"])
    assert r["data"] is None and r["pending_action"]  # 2a dari pintu model → tertunda
    assert e.wp.posts[d["id"]]["status"] == "draft"
    act = r["pending_action"]["id"]
    assert act in e.wp.pending  # muncul di wp-admin → Persetujuan WP-MCP
    assert e.confirm("admin1", act, door=CC)["error"]["code"] == "NOT_AUTHORIZED"
    decide(e.wp, act, "rina")  # admin1 menekan Setujui di wp-admin
    res = e.confirm("admin1", act, door=CC)
    assert res["ok"], res
    assert e.wp.posts[d["id"]]["status"] == "pending"
    audit = [json.loads(x) for x in (e.tmp / "log" / "audit.jsonl").read_text().splitlines()]
    assert audit[-1]["confirmation"]["via"] == "wp_admin" and audit[-1]["acting_as"] == "operator-ai"


def test_wp_admin_approval_respects_roles_and_rejection(env_dir):
    e = env_dir
    pid = _ready_post(e)
    act = e.call("pim1", "approve_and_publish", door=CC, post_id=pid)["pending_action"]["id"]
    decide(e.wp, act, "rina")  # admin-web menyetujui terbit tanpa delegasi → ditolak saat eksekusi
    assert e.confirm("pim1", act, door=CC)["error"]["code"] == "NOT_AUTHORIZED"
    assert e.wp.posts[pid]["status"] == "pending"
    act2 = e.call("pim1", "approve_and_publish", door=CC, post_id=pid)["pending_action"]["id"]
    decide(e.wp, act2, "orang-asing")  # login tak dipetakan
    assert e.confirm("pim1", act2, door=CC)["error"]["code"] == "NOT_AUTHORIZED"
    act3 = e.call("pim1", "approve_and_publish", door=CC, post_id=pid)["pending_action"]["id"]
    decide(e.wp, act3, "kepala", "rejected")
    assert e.confirm("pim1", act3, door=CC)["error"]["code"] == "NOT_AUTHORIZED"
    assert e.services.state.one("SELECT status FROM pending_actions WHERE id=?", (act3,))["status"] == "rejected"


def test_level3_cannot_use_wp_admin_and_otp_attempts_are_limited(env_dir):
    e = env_dir
    d = e.ok("operator-ai", "create_draft", title="Batal", content_markdown="Isi.")
    act = e.call("tech1", "trash_post", door=CC, post_id=d["id"], reason="ganda")["pending_action"]
    assert act["approval_channels"] == ["otp"] and act["id"] not in e.wp.pending
    code = e.notifier.last_otp()
    wrong = "000000" if code != "000000" else "111111"
    for i in range(4):
        assert "Kode salah" in e.confirm("tech1", act["id"], otp=wrong, door=CC)["error"]["message"]
    assert "dibatalkan" in e.confirm("tech1", act["id"], otp=wrong, door=CC)["error"]["message"]
    assert e.confirm("tech1", act["id"], otp=code, door=CC)["error"]["code"] == "EXPIRED"
    assert e.wp.posts[d["id"]]["status"] == "draft"


def test_no_external_channel_means_not_configured(env_dir):
    e = env_dir
    e.notifier.enabled = False
    e.cfg.data["approvals"]["wp_admin"] = False
    d = e.ok("operator-ai", "create_draft", title="X", content_markdown="Isi.")
    assert e.call("admin1", "submit_to_leader", door=CC, post_id=d["id"])["error"]["code"] == "NOT_CONFIGURED"


def test_concurrent_confirm_executes_once(env_dir):
    e = env_dir
    pid = _ready_post(e)
    act = e.call("pim1", "approve_and_publish", post_id=pid)["pending_action"]["id"]
    e.services.state.execute("UPDATE pending_actions SET status='executing' WHERE id=?", (act,))
    assert e.confirm("pim1", act)["error"]["code"] == "EXPIRED"


# --- status WordPress menang atas meta ----------------------------------------
def test_wp_status_overrides_meta(env_dir):
    e = env_dir
    d = e.ok("operator-ai", "create_draft", title="Diterbitkan lewat wp-admin", content_markdown="Isi.")
    e.wp.posts[d["id"]]["status"] = "publish"  # meta tetap 'draft'
    assert e.call("operator-ai", "update_draft", post_id=d["id"], title="timpa")["error"]["code"] == "WORKFLOW"
    assert e.call("admin1", "submit_to_leader", post_id=d["id"])["error"]["code"] == "WORKFLOW"
    assert e.wp.posts[d["id"]]["status"] == "publish"


# --- komentar -------------------------------------------------------------
def test_complaint_words_force_leader_even_if_class_is_benign(env_dir):
    e = env_dir
    d = e.ok("operator-ai", "create_draft", title="Layanan", content_markdown="Isi.")
    c = add_citizen_comment(e.wp, d["id"], "Saya kecewa, ada pungli di loket.")
    r = e.ok("operator-ai", "draft_reply", comment_id=c, reply_class="apresiasi", content="Terima kasih, Bapak/Ibu.")
    assert e.call("admin1", "send_reply", reply_id=r["reply_id"])["error"]["code"] == "NOT_AUTHORIZED"
    p = e.call("pim1", "send_reply", reply_id=r["reply_id"])
    assert p["pending_action"]["readback"]["complaint_flag"] is True


def test_mark_spam_only_on_held_citizen_comments(env_dir):
    e = env_dir
    d = e.ok("operator-ai", "create_draft", title="Layanan", content_markdown="Isi.")
    c = add_citizen_comment(e.wp, d["id"], "Komentar warga yang sudah tampil.")
    e.wp.comments[c]["status"] = "approved"
    assert e.call("operator-ai", "mark_spam", comment_id=c)["error"]["code"] == "INVALID_INPUT"
    e.wp.comments[c]["status"] = "hold"
    assert e.call("operator-ai", "mark_spam", comment_id=c)["ok"]


# --- data pribadi di tag/term ------------------------------------------------
def test_pii_in_tags_and_terms_blocked(env_dir):
    e = env_dir
    r = e.call("operator-ai", "create_draft", title="X", content_markdown="Isi.", tags=["6306011201900003"])
    assert r["error"]["code"] == "PII_BLOCKED" and r["error"]["detail"]["findings"][0]["field"] == "tags[0]"
    assert e.call("operator-ai", "create_term", name="hubungi 081234567890")["error"]["code"] == "PII_BLOCKED"
    audit = (e.tmp / "log" / "audit.jsonl").read_text()
    assert "6306011201900003" not in audit and "081234567890" not in audit


# --- gambar luar di tengah paragraf -------------------------------------------
def test_inline_external_image_is_stripped(env_dir):
    d = env_dir.ok("operator-ai", "create_draft", title="X", content_markdown="Teks ![pixel](https://evil.example/p.gif) lanjut.")
    content = env_dir.wp.posts[d["id"]]["content"]
    assert "evil.example" not in content and "<img" not in content


# --- jalur berkas -------------------------------------------------------------
def test_directory_import_path_prefix_trick(env_dir, tmp_path):
    evil = env_dir.cfgdir.parent / (env_dir.cfgdir.name + "-evil")
    evil.mkdir()
    (evil / "x.md").write_text("# x")
    r = env_dir.call("admin1", "directory_import", path=str(evil / "x.md"))
    assert r["error"]["code"] == "INVALID_INPUT"
    r = env_dir.call("admin1", "directory_import", path=str(env_dir.cfgdir / "secrets.env"))
    assert r["error"]["code"] == "INVALID_INPUT"


# --- pembungkus WP-CLI di balik sudo ------------------------------------------
def test_wp_safe_enforces_whitelist(tmp_path):
    import pytest
    from wp_mcp.config import _packaged_text
    from wp_mcp.errors import CommandNotAllowed
    from wp_mcp.wp_safe import build_argv
    wl = tmp_path / "wl.yaml"
    wl.write_text(_packaged_text("cli_whitelist.yaml"))
    conf = {"wp_bin": "/usr/local/bin/wp", "wp_path": "/var/www/html", "whitelist": str(wl)}
    assert build_argv(["--path=/etc", "plugin", "list", "--status=active"], conf) == [
        "/usr/local/bin/wp", "--path=/var/www/html", "--no-color", "plugin", "list", "--status=active"]
    for bad in (["eval", "system('id');"], ["db", "query", "SELECT 1"], ["user", "create", "x", "y"],
                ["plugin", "list", "--url=evil"], ["plugin", "list", "--ssh=host"], ["--require=/tmp/x.php", "plugin", "list"]):
        with pytest.raises(CommandNotAllowed):
            build_argv(bad, conf)


# --- verifikasi ulang: celah baru ---------------------------------------------
def test_model_door_cannot_use_level1_human_privileges(env_dir):
    e = env_dir
    # perintah "admin" dari pintu model hanya menjadi usulan
    m = e.ok("admin1", "memory_propose", door=CC, kind="style", key="k", value={"benar": "A"}, source="admin_command")
    assert m["status"] == "proposed"
    # data pribadi untuk publik dari pintu model → aksi tertunda, bukan langsung
    r = e.call("admin1", "create_draft", door=CC, title="Pengumuman", confirm_public_pii=True,
               content_markdown="Pemenang: Andi, NIK 6306011201900003.")
    assert r["data"] is None and "DATA PRIBADI" in r["pending_action"]["summary"]
    assert not [p for p in e.wp.posts.values() if p["title"] == "Pengumuman"]
    assert e.confirm("admin1", r["pending_action"]["id"], otp=e.notifier.last_otp(), door=CC)["ok"]
    # HTML mentah dari pintu model → aksi tertunda
    r = e.call("admin1", "create_draft", door=CC, title="Embed", content_markdown="x", allow_html=True)
    assert r["data"] is None and "HTML MENTAH" in r["pending_action"]["summary"]


def test_padded_arguments_cannot_hide_from_approver(env_dir):
    e = env_dir
    from conftest import FILLED_DIRECTORY
    evil = FILLED_DIRECTORY.replace("| P03 | Rina Marlina, S.Kom |", "| P03 | Penyusup Palsu |")
    r = e.call("admin1", "directory_import", door=CC, markdown=" " * 500 + evil, replace=True)
    act = r["pending_action"]
    assert "person 2" in act["summary"] and "GANTI" in act["summary"]
    assert any("Penyusup Palsu" in n for n in act["readback"]["officials"])
    assert "Penyusup Palsu" in json.dumps(e.wp.pending[act["id"]]["readback"])  # terlihat di wp-admin


def test_publish_readback_shows_body_and_leader_changes(env_dir):
    e = env_dir
    pid = _ready_post(e)
    e.ok("pim1", "leader_edit", post_id=pid, instruction="ubah", content_markdown="Isi berita yang diubah pimpinan.")
    rb = e.call("pim1", "approve_and_publish", door=CC, post_id=pid)["pending_action"]["readback"]
    assert "diubah pimpinan" in rb["body_excerpt"] and rb["leader_changes"]


def test_unknown_door_is_treated_as_model_door(env_dir):
    e = env_dir
    d = e.ok("operator-ai", "create_draft", title="X", content_markdown="Isi.")
    r = e.call("admin1", "submit_to_leader", door="telegram", post_id=d["id"])
    assert r["data"] is None and r["pending_action"]


def test_unmapped_login_cannot_veto(env_dir):
    e = env_dir
    pid = _ready_post(e)
    act = e.call("pim1", "approve_and_publish", door=CC, post_id=pid)["pending_action"]["id"]
    decide(e.wp, act, "editor-lain", "rejected")
    e.confirm("pim1", act, door=CC)
    assert e.services.state.one("SELECT status FROM pending_actions WHERE id=?", (act,))["status"] == "pending"
