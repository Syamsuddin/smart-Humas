"""Uji unit: konversi blok, PII, pemeriksa nama, parser Direktori."""

from __future__ import annotations

from conftest import FILLED_DIRECTORY
from wp_mcp.directory_md import parse_directory
from wp_mcp.markdown_blocks import markdown_to_blocks
from wp_mcp.names import check_names, core_name
from wp_mcp.pii import PIIScanner, _valid_nik
from wp_mcp.config import _packaged_text
import yaml


def test_markdown_blocks_basic():
    r = markdown_to_blocks("# H1\n\nPara **tebal**.\n\n1. a\n2. b\n\n<script>x</script>")
    assert '<!-- wp:heading -->\n<h2 class="wp-block-heading">H1</h2>' in r.content
    assert '<!-- wp:list {"ordered":true} -->' in r.content and "<!-- wp:list-item -->" in r.content
    assert "<script>" not in r.content and "&lt;script&gt;" in r.content
    assert r.warnings and "H1" in r.warnings[0]


def test_markdown_rejects_external_images():
    r = markdown_to_blocks("![x](https://evil.example/a.jpg)")
    assert "wp:image" not in r.content and any("sumber luar" in w for w in r.warnings)


def test_nik_validation():
    assert _valid_nik("6306011201900003")
    assert _valid_nik("6306015201900003")       # perempuan: tanggal + 40
    assert not _valid_nik("1234567890123456")   # tanggal 78 → bukan NIK
    assert not _valid_nik("0006011201900003")   # kode provinsi 00


def test_pii_scanner_patterns():
    s = PIIScanner(yaml.safe_load(_packaged_text("pii_patterns.yaml")))
    found = {f.pattern for f in s.scan("HP 0812-3456-7890, email a@gmail.com, npwp 12.345.678.9-012.345, rek. 1234567890")}
    assert {"phone_mobile", "email", "npwp", "bank_account"} <= found
    assert not s.scan("Kantor: humas@contoh.go.id, telepon (0517) 21234")
    assert "[Nomor HP disamarkan]" in s.mask("Hubungi 081234567890")


def test_core_name():
    assert core_name("Drs. H. Ahmad Fauzi, M.AP") == "Ahmad Fauzi"
    assert core_name("Hj. Siti Aminah, S.Pd., M.Pd.") == "Siti Aminah"


def test_title_matching_distinguishes_badan_and_bidang():
    recs = parse_directory(FILLED_DIRECTORY).records
    t = ("Kepala BKPSDM, Rina Marlina, menyampaikan. Kepala Bidang PSDM, Rina Marlina, menjelaskan. "
         "Wakil Bupati Ahmad Fauzi membuka. Bupati Ahmad Fauzi membuka. Bupati Contoh membuka acara.")
    r = check_names(t, recs)
    kinds = [(f["type"], f.get("name"), f.get("title_in_text")) for f in r.findings]
    assert ("TITLE_MISMATCH", "Rina Marlina", "Kepala BKPSDM") in kinds
    assert ("TITLE_MISMATCH", "Ahmad Fauzi", "Wakil Bupati") in kinds
    assert not any(k[2] == "Kepala Bidang PSDM" for k in kinds)
    assert not any(k[0] == "UNVERIFIED_NAME" for k in kinds)  # "Bupati Contoh" adalah nama daerah, bukan orang


def test_fuzzy_fix_and_unverified_mark():
    recs = parse_directory(FILLED_DIRECTORY).records
    r = check_names("Kepala Bidang PSDM, Rina Marlena, menjelaskan. Camat Baru, Joko Susilo, hadir.", recs)
    assert "Rina Marlina" in r.text and "[NAMA BELUM TERVERIFIKASI: Joko Susilo]" in r.text
    assert not r.as_dict()["publishable"]


def test_parse_directory_skips_empty_template_rows():
    p = parse_directory(_packaged_text("direktori-redaksi.md"))
    assert not [r for r in p.records if r["kind"] in ("person", "unit", "leader")]
    assert any("belum berisi nama" in w for w in p.warnings)
