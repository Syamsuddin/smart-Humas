"""Konteks redaksi: panggilan PERTAMA setiap skill.

Mengembalikan gaya rumah, identitas lokal dari Direktori (nama resmi, baris tanggal-tempat, kredit foto,
penanda sumber), pejabat aktif, peta kategori, aturan gaya lokal, memori aktif yang relevan, spesifikasi foto,
dan apa yang boleh dilakukan peran pemanggil. Skill tidak perlu membaca berkas di laptop: semua dari server.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from ..policy import LEVEL_DEFAULT_ROLES, REGISTRY, ToolContext, tool
from . import _common as c
from .directory import directory_status

Purpose = Literal["berita", "halaman", "balas-komentar", "siapkan-direktori", "umum"]


def _kv(recs: list[dict], kind: str) -> dict[str, str]:
    return {r["key"]: r["record"].get("nilai", "") for r in recs if r["kind"] == kind}


def _allowed_tools(role: str) -> list[str]:
    out = []
    for name, spec in REGISTRY.items():
        if role in (spec.roles or LEVEL_DEFAULT_ROLES[spec.level]):
            out.append(name)
    return sorted(out)


@tool("get_editorial_context", level="0", group="editorial")
def get_editorial_context(ctx: ToolContext, purpose: Purpose = "berita") -> dict:
    """Panggil PERTAMA di setiap skill. Berisi pedoman gaya rumah, identitas lokal dari Direktori, pejabat aktif,
    peta kategori, aturan gaya lokal, memori aktif, spesifikasi foto, dan tool yang boleh dipakai peran Anda."""
    recs = c.directory_records(ctx, verified_only=True)
    pemda, opd = _kv(recs, "pemda"), _kv(recs, "opd")
    people = [{"nama": r["record"].get("nama_lengkap_bergelar"), "jabatan": r["record"].get("jabatan_resmi") or r["record"].get("jabatan"),
               "sebutan_pertama": r["record"].get("sebutan_pertama"), "sebutan_berikutnya": r["record"].get("sebutan_berikutnya")}
              for r in recs if r["kind"] in ("leader", "person")]
    out: dict[str, Any] = {
        "role": ctx.actor.role, "actor": ctx.actor.label,
        "style_guide": ctx.cfg.style_guide,
        "local": {
            "pemda": pemda.get("nama_resmi"), "pemda_singkatan": pemda.get("singkatan_resmi"),
            "pemda_singkatan_dilarang": pemda.get("singkatan_dilarang"),
            "dateline": pemda.get("format_dateline"), "opd": opd.get("nama_resmi"),
            "opd_singkatan": opd.get("singkatan_resmi"), "opd_singkatan_dilarang": opd.get("singkatan_dilarang"),
            "kredit_foto": opd.get("kredit_foto"), "penanda_sumber_berita": opd.get("penanda_sumber_berita"),
            "alamat_kantor": opd.get("alamat_kantor"), "url_profil": opd.get("url_profil"),
        },
        "officials": people,
        "units": [{"nama": r["record"].get("nama_resmi_unit"), "singkatan": r["record"].get("singkatan")}
                  for r in recs if r["kind"] == "unit"],
        "local_style_rules": [r["record"] for r in recs if r["kind"] == "style"],
        "category_map": {r["key"]: {"kategori": r["record"].get("kategori_wordpress"), "tag_wajib": r["record"].get("tag_wajib")}
                         for r in recs if r["kind"] == "category"},
        "programs": [r["record"] for r in recs if r["kind"] == "program"],
        "places": [r["record"].get("nama_resmi") for r in recs if r["kind"] == "place"],
        "media_spec": ctx.cfg.get("media"),
        "directory_status": directory_status(ctx)["status"],
        "your_tools": _allowed_tools(ctx.actor.role),
        "workflow": {
            "operator-ai": "Menyusun dan merevisi draft; tidak mengajukan, tidak menerbitkan.",
            "admin-web": "Memerintahkan pembuatan dan perbaikan, lalu submit_to_leader. Terbit hanya dengan delegasi.",
            "pimpinan": "Review akhir, leader_edit untuk perubahan kecil, approve_and_publish atau return_to_admin.",
        },
    }
    kinds = {"berita": ["style", "story", "program", "place"], "halaman": ["style", "program"],
             "balas-komentar": ["reply", "program", "style"], "siapkan-direktori": [], "umum": ["style"]}[purpose]
    if kinds:
        rows = ctx.state.query(
            f"SELECT kind, key, value_json FROM memory WHERE status='active' AND kind IN ({','.join('?' * len(kinds))}) "
            "AND (valid_until IS NULL OR valid_until > ?) ORDER BY used_count DESC, updated_at DESC LIMIT 40",
            (*kinds, ctx.now))
        out["memory"] = [{"kind": r["kind"], "key": r["key"], "value": json.loads(r["value_json"])} for r in rows]
    if out["directory_status"] != "lengkap-wajib":
        out["attention"] = ("Direktori belum lengkap-wajib. Nama yang tidak terdaftar akan ditandai dan menghambat "
                            "penerbitan. Sarankan admin menjalankan /siapkan-direktori.")
    return out
