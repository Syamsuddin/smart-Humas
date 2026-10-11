"""Kebijakan: peran, PII, batas laju, idempotensi, parameter internal, audit."""

from __future__ import annotations

import json


def test_internal_params_cannot_be_injected(env_dir):
    e = env_dir
    d = e.ok("operator-ai", "create_draft", title="Uji", content_markdown="Isi.")
    e.ok("admin1", "submit_to_leader", post_id=d["id"])
    # admin-web mencoba memalsukan delegasi
    r = e.call("admin1", "approve_and_publish", post_id=d["id"], _delegation_id=1)
    assert r["error"]["code"] == "NOT_AUTHORIZED"


def test_pii_blocks_nik_unless_human_confirms(env_dir):
    e = env_dir
    body = "Pemenang seleksi atas nama Andi, NIK 6306011201900003, alamat Kota Baru."
    r = e.call("operator-ai", "create_draft", title="Pengumuman", content_markdown=body)
    assert r["error"]["code"] == "PII_BLOCKED"
    assert r["error"]["detail"]["findings"][0]["pattern"] == "nik"
    # operator-ai tidak bisa melewati dengan confirm_public_pii
    r = e.call("operator-ai", "create_draft", title="Pengumuman", content_markdown=body, confirm_public_pii=True)
    assert r["error"]["code"] == "PII_BLOCKED"
    r = e.call("admin1", "create_draft", title="Pengumuman", content_markdown=body, confirm_public_pii=True)
    assert r["ok"] and r["warnings"][0]["code"] == "PII_CONFIRMED_PUBLIC"


def test_office_email_is_not_pii(env_dir):
    r = env_dir.call("operator-ai", "create_draft", title="Kontak", content_markdown="Hubungi humas@contoh.go.id.")
    assert r["ok"], r


def test_rate_limit(env_dir):
    e = env_dir
    e.cfg.data["limits"]["writes_per_10min"] = 3
    for i in range(3):
        e.ok("operator-ai", "create_draft", title=f"T{i}", content_markdown="x")
    r = e.call("operator-ai", "create_draft", title="T4", content_markdown="x")
    assert r["error"]["code"] == "RATE_LIMITED"
    assert any("Batas laju" in t for _, t in e.notifier.sent)
    e.clock.advance(601)
    assert e.call("operator-ai", "create_draft", title="T5", content_markdown="x")["ok"]


def test_idempotency_replay(env_dir):
    e = env_dir
    a = e.call("operator-ai", "create_draft", title="Sama", content_markdown="x", idempotency_key="tg:1:55")
    b = e.call("operator-ai", "create_draft", title="Sama", content_markdown="x", idempotency_key="tg:1:55")
    assert a["data"]["id"] == b["data"]["id"]
    assert b["warnings"][-1]["code"] == "IDEMPOTENT_REPLAY"
    assert len([p for p in e.wp.posts.values() if p["title"] == "Sama"]) == 1


def test_unknown_actor_and_tool(env):
    assert env.call("hacker", "list_posts")["error"]["code"] == "NOT_CONFIGURED"
    assert env.call("admin1", "drop_database")["error"]["code"] == "NOT_FOUND"
    assert env.call("admin1", "list_posts", bogus=1)["error"]["code"] == "INVALID_INPUT"


def test_operator_cannot_create_category_or_change_directory(env):
    assert env.call("operator-ai", "create_term", name="Baru", taxonomy="category")["error"]["code"] == "NOT_AUTHORIZED"
    assert env.call("operator-ai", "create_term", name="tag baru", taxonomy="post_tag")["ok"]
    r = env.call("operator-ai", "directory_set", kind="person", record={"kode": "P9", "nama_lengkap_bergelar": "X"})
    assert r["error"]["code"] == "NOT_AUTHORIZED"


def test_audit_masks_pii_and_secrets(env_dir):
    e = env_dir
    e.call("operator-ai", "create_draft", title="Uji", content_markdown="NIK 6306011201900003")
    lines = [json.loads(x) for x in (e.tmp / "log" / "audit.jsonl").read_text().splitlines()]
    blocked = [l for l in lines if l["result"] == "PII_BLOCKED"][-1]
    assert "6306011201900003" not in json.dumps(blocked)
    assert blocked["actor"] == "operator-ai" and blocked["role"] == "operator-ai"


def test_cli_whitelist(env):
    from wp_mcp.errors import CommandNotAllowed
    cli = env.services.cli
    assert cli.level_of(["plugin", "list"]) == "0"
    assert cli.level_of(["plugin", "update", "akismet"]) == "3"
    for bad in (["eval", "echo 1;"], ["db", "query", "DROP TABLE wp_posts"], ["plugin", "list", "--exec=system('id')"],
                ["user", "create", "x", "x@y"]):
        try:
            cli.level_of(bad)
        except CommandNotAllowed:
            continue
        raise AssertionError(f"tidak ditolak: {bad}")
