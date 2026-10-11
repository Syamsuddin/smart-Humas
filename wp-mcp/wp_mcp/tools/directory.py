"""Direktori Resmi: nama pemda, OPD, unit, pejabat, tempat, program, gaya, kategori, redaksi.

Hanya diubah lewat pintu manusia (admin-web/pimpinan). operator-ai hanya membaca dan memeriksa.
Isinya disuplai lewat wawancara singkat skill /siapkan-direktori.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from ..directory_md import KEY_FIELD, KEYVALUE_KINDS, SECTION_KIND, completeness, export_directory, parse_directory
from ..errors import InvalidInput, NotFound, PIIBlocked
from ..names import check_names
from ..policy import HUMAN_ROLES, ToolContext, tool
from . import _common as c

KINDS = sorted(set(SECTION_KIND.values()))
PRIORITY = ["B", "D", "C", "A", "A.1", "I", "H.1"]
FORBIDDEN_FIELDS = {"nip", "nik", "hp", "no_hp", "nomor_hp", "alamat_rumah", "telepon_pribadi"}


def _upsert(ctx: ToolContext, kind: str, key: str, record: dict, verified: bool, source: str) -> None:
    ctx.state.execute(
        "INSERT INTO directory(kind, key, record_json, verified, source, updated_at, updated_by) VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT(kind, key) DO UPDATE SET record_json=excluded.record_json, verified=excluded.verified, "
        "source=excluded.source, updated_at=excluded.updated_at, updated_by=excluded.updated_by",
        (kind, key, json.dumps(record, ensure_ascii=False), int(verified), source, ctx.now, ctx.actor.id))


def _log(ctx: ToolContext, section: str, change: str) -> None:
    ctx.state.execute("INSERT INTO directory_log(ts, section, change, actor) VALUES (?,?,?,?)",
                      (ctx.now, section, change[:300], ctx.actor.id))


def _guard_record(ctx: ToolContext, record: dict) -> None:
    bad = [k for k in record if k.lower() in FORBIDDEN_FIELDS]
    if bad:
        raise InvalidInput(f"Direktori hanya informasi publik; bidang {bad} tidak boleh disimpan.")
    findings = ctx.scanner.scan(json.dumps(record, ensure_ascii=False))
    findings = [f for f in findings if f.pattern != "email"]  # email kantor resmi boleh
    if findings:
        raise PIIBlocked("Rekaman Direktori memuat pola data pribadi.", detail={"findings": [f.as_dict() for f in findings]})


@tool("directory_status", level="0", group="directory")
def directory_status(ctx: ToolContext) -> dict:
    """Kelengkapan Direktori: bidang wajib yang kosong atau belum disahkan, urut prioritas wawancara
    (B → D → C → A → A.1 → I → H.1). Dipakai skill /siapkan-direktori untuk menentukan pertanyaan berikutnya."""
    recs = c.directory_records(ctx)
    comp = completeness(recs)

    def prio(item: str) -> int:
        sec = item.split(" ")[0].split(".")[0] if not item.startswith("A.1") else "A.1"
        return PRIORITY.index(sec) if sec in PRIORITY else len(PRIORITY)

    comp["missing"] = sorted(comp["missing"], key=prio)
    comp["unverified"] = sorted(comp["unverified"], key=prio)
    comp["counts"] = {k: sum(1 for r in recs if r["kind"] == k) for k in KINDS}
    comp["meta"] = {k: ctx.state.meta_get(k) for k in ("situs_url", "opd_pemilik", "pemda", "diperbarui", "disahkan_oleh")}
    return comp


@tool("directory_lookup", level="0", group="directory")
def directory_lookup(ctx: ToolContext, text: str | None = None, kind: str | None = None,
                     include_unverified: bool = False) -> dict:
    """Cari di Direktori (bawaan: hanya yang sudah disahkan). kind: pemda | leader | opd | unit | person |
    person_history | partner | place | program | style | category | editor."""
    recs = c.directory_records(ctx, verified_only=not include_unverified)
    if kind:
        recs = [r for r in recs if r["kind"] == kind]
    if text:
        t = text.lower()
        recs = [r for r in recs if t in (r["key"] + " " + json.dumps(r["record"], ensure_ascii=False)).lower()]
    return {"items": recs[:200], "count": len(recs)}


def _describe_set(ctx: ToolContext, args: dict) -> dict:
    rec = args.get("record") or {}
    shown = {k: " ".join(str(v).split())[:200] for k, v in rec.items()}
    return {"summary": f"Direktori: simpan {args.get('kind')} " + "; ".join(f"{k}={v}" for k, v in shown.items()),
            "impact": ["dipakai pemeriksa nama di semua berita berikutnya"], "readback": {"kind": args.get("kind"), "record": shown}}


def _describe_import(ctx: ToolContext, args: dict) -> dict:
    text = args.get("markdown") or ""
    if args.get("path"):
        text = f"(berkas {args['path']})"
    parsed = parse_directory(args.get("markdown") or "") if args.get("markdown") else None
    counts: dict[str, int] = {}
    names: list[str] = []
    if parsed:
        for r in parsed.records:
            counts[r["kind"]] = counts.get(r["kind"], 0) + 1
            if r["kind"] in ("person", "leader"):
                names.append(f"{r['record'].get('nama_lengkap_bergelar')} — {r['record'].get('jabatan_resmi') or r['record'].get('jabatan')}")
    mode = "GANTI seluruh jenis yang ada di berkas" if args.get("replace") else "gabungkan"
    return {"summary": f"Direktori: impor {sum(counts.values())} rekaman ({mode}): "
                       + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())),
            "impact": ["dipakai pemeriksa nama di semua berita berikutnya"] + (["rekaman lama jenis yang sama dihapus"] if args.get("replace") else []),
            "readback": {"counts": counts, "officials": names[:60], "source": text if args.get("path") else "teks markdown"}}


def _describe_retire(ctx: ToolContext, args: dict) -> dict:
    return {"summary": f"Direktori: pindahkan pejabat {args.get('kode')} ke riwayat sampai {args.get('sampai')}"
                       + (f", digantikan {args.get('digantikan_oleh')}" if args.get("digantikan_oleh") else ""),
            "impact": ["nama ini akan ditandai bila ditulis dengan jabatan lamanya"]}


@tool("directory_set", level="2a", roles=HUMAN_ROLES, describe_pending=_describe_set, group="directory")
def directory_set(ctx: ToolContext, kind: str, record: dict[str, Any], verified: bool = True,
                  source: str = "admin") -> dict:
    """Simpan atau perbarui satu rekaman Direktori setelah admin membalas 'sah'.
    Untuk pemda/opd: record = {"bidang": "...", "nilai": "..."}. Untuk lainnya, kunci mengikuti kolom templat
    (unit: kode; person: kode; leader: jabatan; place: nama_resmi; category: jenis_berita; editor: peran)."""
    if kind not in KINDS:
        raise InvalidInput(f"kind tidak dikenal. Pilihan: {', '.join(KINDS)}")
    _guard_record(ctx, record)
    if kind in KEYVALUE_KINDS:
        key = record.get("bidang")
        if not key:
            raise InvalidInput("record untuk pemda/opd harus berisi 'bidang' dan 'nilai'.")
    else:
        key = record.get(KEY_FIELD[kind])
        if not key:
            raise InvalidInput(f"record untuk {kind} harus berisi '{KEY_FIELD[kind]}'.")
    _upsert(ctx, kind, str(key), record, verified, source)
    _log(ctx, kind, f"set {key}")
    return {"kind": kind, "key": key, "verified": verified, "status": completeness(c.directory_records(ctx))["status"]}


@tool("directory_retire_person", level="2a", roles=HUMAN_ROLES, describe_pending=_describe_retire, group="directory")
def directory_retire_person(ctx: ToolContext, kode: str, sampai: str, digantikan_oleh: str | None = None) -> dict:
    """Pejabat mutasi/pensiun: pindahkan ke riwayat (D.1). Berita lama tetap bisa dijelaskan,
    dan pemeriksa nama menandai bila nama lama ditulis dengan jabatan yang sudah tidak dipegang."""
    row = ctx.state.one("SELECT * FROM directory WHERE kind='person' AND key=?", (kode,))
    if not row:
        raise NotFound(f"Pejabat {kode} tidak ada di Direktori.")
    rec = json.loads(row["record_json"])
    hist = {"kode": f"{kode}@{sampai}", "nama_lengkap_bergelar": rec.get("nama_lengkap_bergelar", ""),
            "jabatan_saat_itu": rec.get("jabatan_resmi", ""), "sampai": sampai, "digantikan_oleh": digantikan_oleh or ""}
    _upsert(ctx, "person_history", hist["kode"], hist, True, "admin")
    ctx.state.execute("DELETE FROM directory WHERE kind='person' AND key=?", (kode,))
    _log(ctx, "D", f"{kode} ke riwayat sampai {sampai}")
    return {"moved": kode, "history_key": hist["kode"], "next": "Isi pejabat pengganti dengan directory_set kind=person."}


@tool("directory_import", level="2a", roles=HUMAN_ROLES, describe_pending=_describe_import, group="directory")
def directory_import(ctx: ToolContext, markdown: str | None = None, path: str | None = None, replace: bool = False) -> dict:
    """Impor berkas direktori-redaksi.md (isi teks atau path di /etc/wp-mcp). replace=true mengganti seluruh
    rekaman jenis yang ada di berkas; bawaan menggabungkan."""
    if not markdown and not path:
        raise InvalidInput("Isi markdown atau path.")
    if path:
        p = Path(path).resolve()
        if not p.is_relative_to(ctx.cfg.config_dir.resolve()) or p.suffix != ".md":
            raise InvalidInput("path harus berkas .md di dalam direktori konfigurasi WP-MCP.")
        markdown = p.read_text(encoding="utf-8")
    parsed = parse_directory(markdown or "")
    for r in parsed.records:
        _guard_record(ctx, r["record"])
    if replace:
        for kind in {r["kind"] for r in parsed.records}:
            ctx.state.execute("DELETE FROM directory WHERE kind=?", (kind,))
    for r in parsed.records:
        _upsert(ctx, r["kind"], r["key"], r["record"], r["verified"], r["source"])
    for k, v in parsed.meta.items():
        if v is not None:
            ctx.state.meta_set(k, str(v))
    _log(ctx, "*", f"import {len(parsed.records)} rekaman")
    return {"imported": len(parsed.records), "warnings": parsed.warnings, **completeness(c.directory_records(ctx))}


@tool("directory_export", level="0", group="directory")
def directory_export(ctx: ToolContext) -> dict:
    """Ekspor Direktori ke format direktori-redaksi.md untuk dicek atau dipindah ke situs lain."""
    recs = c.directory_records(ctx)
    meta = {k: ctx.state.meta_get(k, "") for k in ("dosir", "versi_skema", "situs_url", "opd_pemilik", "pemda",
                                                   "diperbarui", "disahkan_oleh")}
    meta["dosir"] = "direktori-redaksi"
    meta["versi_skema"] = meta.get("versi_skema") or "1.0"
    meta["diperbarui"] = date.today().isoformat()
    meta["status"] = completeness(recs)["status"]
    logs = [{"tanggal": date.fromtimestamp(r["ts"]).isoformat(), "bagian": r["section"], "perubahan": r["change"],
             "oleh": r["actor"]} for r in ctx.state.query("SELECT * FROM directory_log ORDER BY ts DESC LIMIT 30")]
    return {"markdown": export_directory(meta, recs, logs)}


@tool("verify_names", level="0", group="directory")
def verify_names(ctx: ToolContext, text: str, mark: bool = True) -> dict:
    """Periksa nama pejabat, OPD, singkatan, dan tempat terhadap Direktori Resmi. Mengembalikan teks yang sudah
    dikoreksi (ejaan salah → resmi; nama tak dikenal ditandai [NAMA BELUM TERVERIFIKASI: ...]; jabatan tidak cocok
    → [JABATAN PERLU DICEK: ...]) serta pertanyaan konfirmasi untuk wawancara mini."""
    return check_names(text, c.directory_records(ctx, verified_only=True), mark=mark).as_dict()
