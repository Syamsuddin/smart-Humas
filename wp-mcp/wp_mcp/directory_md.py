"""Parser dan pengekspor berkas direktori-redaksi.md (format markdown bertabel).

Setiap bagian dipetakan ke satu jenis rekaman:
  A   pemda          (bidang → nilai)      A.1 leader   (per jabatan pimpinan daerah)
  B   opd            (bidang → nilai)      C   unit     (per kode unit)
  D   person         (per kode pejabat)    D.1 person_history
  E   partner        F place               G   program
  H   style          H.1 category          I   editor
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml

EMPTY = {"", "[kosong]", "-", "—"}

SECTION_KIND = {
    "A": "pemda", "A.1": "leader", "B": "opd", "C": "unit", "D": "person", "D.1": "person_history",
    "E": "partner", "F": "place", "G": "program", "H": "style", "H.1": "category", "I": "editor",
}
KEY_FIELD = {
    "leader": "jabatan", "unit": "kode", "person": "kode", "person_history": "kode", "partner": "nama_resmi",
    "place": "nama_resmi", "program": "nama_program", "style": "aturan", "category": "jenis_berita", "editor": "peran",
}
KEYVALUE_KINDS = {"pemda", "opd"}

REQUIRED = {
    "pemda": ["nama_resmi", "singkatan_resmi", "ibu_kota", "format_dateline"],
    "opd": ["nama_resmi", "singkatan_resmi", "alamat_kantor", "kredit_foto", "penanda_sumber_berita"],
}
SECTION_TITLES = {
    "A": "Identitas pemerintah daerah", "A.1": "Pimpinan daerah", "B": "OPD pemilik website",
    "C": "Unit kerja di dalam OPD", "D": "Pejabat struktural", "D.1": "Riwayat pejabat",
    "E": "OPD dan instansi mitra yang sering disebut", "F": "Tempat yang sering disebut",
    "G": "Program dan kegiatan rutin", "H": "Gaya redaksi khusus OPD", "H.1": "Peta kategori WordPress",
    "I": "Redaksi website",
}
COLUMNS = {
    "leader": ["jabatan", "nama_lengkap_bergelar", "sebutan_pertama", "sebutan_berikutnya", "sejak", "sumber", "verif"],
    "unit": ["kode", "nama_resmi_unit", "singkatan", "induk", "sumber", "verif"],
    "person": ["kode", "nama_lengkap_bergelar", "jabatan_resmi", "unit", "sebutan_berikutnya", "sejak", "ejaan_salah", "sumber", "verif"],
    "person_history": ["kode", "nama_lengkap_bergelar", "jabatan_saat_itu", "sampai", "digantikan_oleh"],
    "partner": ["nama_resmi", "singkatan_resmi", "singkatan_dilarang", "pimpinan_bergelar", "jabatan_pimpinan", "verif"],
    "place": ["nama_resmi", "ejaan_salah", "jenis", "kecamatan", "verif"],
    "program": ["nama_program", "singkatan", "tujuan_satu_kalimat", "dasar_hukum", "url_halaman", "tag_baku", "berlaku_sampai"],
    "style": ["aturan", "contoh_benar", "contoh_salah"],
    "category": ["jenis_berita", "kategori_wordpress", "tag_wajib"],
    "editor": ["peran", "nama", "kanal"],
}


@dataclass
class ParsedDirectory:
    meta: dict[str, Any] = field(default_factory=dict)
    records: list[dict[str, Any]] = field(default_factory=list)  # {kind, key, record, verified, source}
    warnings: list[str] = field(default_factory=list)


def _clean(cell: str) -> str:
    v = cell.strip().strip("`").strip()
    return "" if v.lower() in EMPTY else v


def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def _heading_section(line: str) -> str | None:
    m = re.match(r"^#{2,3}\s+([A-Z](?:\.\d+)?)\.?\s", line)
    return m.group(1) if m else None


def _is_verified(value: str) -> bool:
    return value.strip().lower() in {"ya", "yes", "y", "true", "sah", "1"}


def parse_directory(text: str) -> ParsedDirectory:
    out = ParsedDirectory()
    body = text
    fm = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if fm:
        try:
            out.meta = yaml.safe_load(fm.group(1)) or {}
        except yaml.YAMLError as exc:
            out.warnings.append(f"Frontmatter tidak terbaca: {exc}")
        body = text[fm.end():]
    approved = bool(_clean(str(out.meta.get("disahkan_oleh") or "")))

    section: str | None = None
    header: list[str] | None = None
    for raw in body.splitlines():
        line = raw.rstrip()
        sec = _heading_section(line)
        if sec:
            section, header = sec, None
            continue
        if line.startswith("#"):
            section, header = None, None
            continue
        if not section or section not in SECTION_KIND or not line.strip().startswith("|"):
            if not line.strip().startswith("|"):
                header = None
            continue
        cells = _split_row(line)
        if header is None:
            header = [c.strip().lower() for c in cells]
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue
        kind = SECTION_KIND[section]
        row = {header[i]: _clean(cells[i]) if i < len(cells) else "" for i in range(len(header))}
        if kind in KEYVALUE_KINDS:
            fld = row.get("bidang", "")
            if not fld:
                continue
            value = row.get("nilai", "")
            out.records.append({"kind": kind, "key": fld, "record": {"bidang": fld, "nilai": value},
                                "verified": bool(value) and approved, "source": "direktori-md"})
            continue
        key_field = KEY_FIELD[kind]
        key = row.get(key_field, "")
        payload = {k: v for k, v in row.items() if k != key_field and v}
        if not key:
            continue
        name_field = {"unit": "nama_resmi_unit", "person": "nama_lengkap_bergelar",
                      "leader": "nama_lengkap_bergelar"}.get(kind)
        if name_field and not payload.get(name_field):
            out.warnings.append(f"Bagian {section} baris '{key}' belum berisi nama; dilewati.")
            continue
        if kind == "category" and not payload.get("kategori_wordpress"):
            continue
        if kind == "style" and not (payload.get("contoh_benar") or payload.get("contoh_salah")):
            continue
        verified = _is_verified(row.get("verif", "")) if "verif" in row else approved
        out.records.append({"kind": kind, "key": key, "record": {key_field: key, **payload},
                            "verified": verified, "source": row.get("sumber") or "direktori-md"})
    return out


def completeness(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Hitung bidang wajib yang masih kosong atau belum disahkan (bagian A, A.1, B, C, D, I)."""
    by_kind: dict[str, list[dict]] = {}
    for r in records:
        by_kind.setdefault(r["kind"], []).append(r)
    missing: list[str] = []
    unverified: list[str] = []
    for kind, fields in REQUIRED.items():
        have = {r["key"]: r for r in by_kind.get(kind, [])}
        sec = "A" if kind == "pemda" else "B"
        for f in fields:
            r = have.get(f)
            if not r or not r["record"].get("nilai"):
                missing.append(f"{sec}.{f}")
            elif not r["verified"]:
                unverified.append(f"{sec}.{f}")
    for kind, sec, label in (("leader", "A.1", "pimpinan daerah"), ("unit", "C", "unit kerja"),
                             ("person", "D", "pejabat struktural"), ("editor", "I", "admin redaksi")):
        rows = by_kind.get(kind, [])
        if not rows:
            missing.append(f"{sec} (minimal satu {label})")
        else:
            unverified += [f"{sec}.{r['key']}" for r in rows if not r["verified"]]
    total_required = sum(len(v) for v in REQUIRED.values()) + 4
    status = "lengkap-wajib" if not missing and not unverified else "draft"
    return {"status": status, "missing": missing, "unverified": unverified,
            "filled_required": total_required - len(missing), "total_required": total_required}


def export_directory(meta: dict[str, Any], records: list[dict[str, Any]], log: list[dict[str, Any]] | None = None) -> str:
    """Tulis ulang direktori ke format markdown yang sama dengan templat."""
    by_kind: dict[str, list[dict]] = {}
    for r in records:
        by_kind.setdefault(r["kind"], []).append(r)
    lines = ["---", yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip(), "---", "",
             "# Direktori Redaksi Website OPD", ""]
    for sec, title in SECTION_TITLES.items():
        kind = SECTION_KIND[sec]
        lines += [f"{'###' if '.' in sec else '##'} {sec}. {title}", ""]
        if kind in KEYVALUE_KINDS:
            lines += ["| Bidang | Nilai |", "|---|---|"]
            fields = REQUIRED.get(kind, [])
            have = {r["key"]: r for r in by_kind.get(kind, [])}
            for f in fields + [k for k in have if k not in fields]:
                v = have.get(f, {}).get("record", {}).get("nilai") or "[KOSONG]"
                lines.append(f"| {f} | {v} |")
        else:
            cols = COLUMNS[kind]
            lines += ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
            for r in by_kind.get(kind, []):
                rec = dict(r["record"])
                if "verif" in cols:
                    rec["verif"] = "ya" if r.get("verified") else "tidak"
                if "sumber" in cols:
                    rec.setdefault("sumber", r.get("source") or "")
                lines.append("| " + " | ".join(str(rec.get(c, "")) for c in cols) + " |")
        lines.append("")
    lines += ["## Log perubahan", "", "| tanggal | bagian | perubahan | oleh |", "|---|---|---|---|"]
    for e in log or []:
        lines.append(f"| {e['tanggal']} | {e['bagian']} | {e['perubahan']} | {e['oleh']} |")
    return "\n".join(lines) + "\n"
