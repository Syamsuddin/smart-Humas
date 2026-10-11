"""Pemeriksa nama pejabat, OPD, dan tempat terhadap Direktori Resmi.

Prinsip: salah tulis nama tidak dicegah dengan berharap model teliti, tetapi dengan pemeriksa
mekanis yang tidak bisa dibujuk.

  - ejaan salah yang tercatat          → diganti otomatis ke bentuk resmi (AUTO_FIXED)
  - singkatan terlarang                → diganti singkatan resmi (ABBREV_FIXED)
  - nama mirip nama pejabat terdaftar  → diganti dan dilaporkan (FUZZY_FIXED)
  - nama di samping jabatan, tak dikenal → ditandai [NAMA BELUM TERVERIFIKASI: ...]
  - nama dikenal, jabatan tidak cocok  → ditandai [JABATAN PERLU DICEK: ...]

Hanya rekaman Direktori yang `verified` yang dipakai.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Iterable

UNVERIFIED_MARK = "NAMA BELUM TERVERIFIKASI"
TITLE_MARK = "JABATAN PERLU DICEK"
BLOCKING_MARKERS = (f"[{UNVERIFIED_MARK}", f"[{TITLE_MARK}", "[BELUM ADA DI BAHAN", "[BELUM ADA DI SUMBER",
                    "[KUTIPAN:", "[KOSONG]")

DEGREE_PREFIX = {"h", "hj", "dr", "drs", "dra", "ir", "prof", "kh", "ust", "ustadz", "ns", "drg", "apt", "tgk"}
STOP_WORDS = {
    "kabupaten", "kota", "provinsi", "dinas", "badan", "bidang", "bagian", "kantor", "pemerintah", "kecamatan",
    "desa", "kelurahan", "sekretariat", "daerah", "republik", "indonesia", "negeri", "rumah", "sakit", "umum",
    "kepala", "sekretaris", "bupati", "wakil", "wali", "gubernur", "camat", "lurah", "selaku", "dalam", "pada",
    "senin", "selasa", "rabu", "kamis", "jumat", "sabtu", "minggu", "januari", "februari", "maret", "april",
    "mei", "juni", "juli", "agustus", "september", "oktober", "november", "desember", "aula", "gedung",
    "ruang", "pendopo", "masjid", "the", "dan", "atau", "pengembangan", "sumber", "daya", "manusia", "dewan",
}
TITLE_KEYWORDS = [
    "Wakil Wali Kota", "Wali Kota", "Wakil Bupati", "Bupati", "Wakil Gubernur", "Gubernur", "Sekretaris Daerah",
    "Asisten", "Staf Ahli", "Kepala", "Sekretaris", "Plt\\.", "Plh\\.", "Camat", "Lurah", "Kades", "Kabid", "Kasubbag",
    "Kasubag", "Kasi", "Kabag", "Direktur", "Ketua", "Sekda", "Inspektur", "Kapolres", "Dandim", "Kajari",
]
_TITLE_RX = "(?:" + "|".join(TITLE_KEYWORDS) + ")"
_NAME_TOKEN = r"(?:(?:H|Hj|Dr|Drs|Dra|Ir|Prof|KH)\.\s*)*[A-Z][A-Za-z'’\-]+(?:,\s*[A-Z][A-Za-z.\-]*\.[A-Za-z.]*)*"
_NAME_SEQ = rf"{_NAME_TOKEN}(?:\s+{_NAME_TOKEN}){{0,4}}"
_AFTER_NAME = (r"(?=\s*,|\s*\.(?:\s|$)|\s+(?:mengatakan|menyampaikan|membuka|menutup|menjelaskan|menegaskan|mengungkapkan|"
               r"menyebutkan|meminta|mengajak|memimpin|meninjau|melantik|selaku|dalam|saat|pada|di|yang|bersama|"
               r"didampingi|beserta|juga|turut|hadir)\b|\s*$)")

PATTERN_COMMA = re.compile(rf"(?P<title>\b{_TITLE_RX}[^,.;\n]{{0,90}}),\s+(?P<name>{_NAME_SEQ}){_AFTER_NAME}")
PATTERN_DIRECT = re.compile(
    rf"(?P<title>\b(?:Wakil Wali Kota|Wali Kota|Wakil Bupati|Bupati|Wakil Gubernur|Gubernur|Camat|Lurah|Sekda|Kades|Plt\.|Plh\.))"
    rf"\s+(?P<name>{_NAME_SEQ}){_AFTER_NAME}")
PATTERN_SELAKU = re.compile(rf"(?P<name>{_NAME_SEQ})\s+selaku\s+(?P<title>[^,.;\n]{{3,90}})")


def core_name(name: str) -> str:
    """Nama tanpa gelar: 'Drs. H. Ahmad Fauzi, M.AP' → 'Ahmad Fauzi'."""
    base = name.split(",")[0]
    tokens = [t for t in re.split(r"\s+", base.strip()) if t]
    kept = [t for t in tokens if t.rstrip(".").lower() not in DEGREE_PREFIX and not re.fullmatch(r"[A-Z]\.", t)]
    return " ".join(kept).strip(" .")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _sig_tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]{3,}", s.lower()) if t not in {"dan", "the", "untuk", "pada", "yang"}}


@dataclass
class Person:
    canonical: str
    core: str
    title: str
    title_alt: str = ""
    wrong: list[str] = field(default_factory=list)
    current: bool = True


@dataclass
class Org:
    official: str
    abbrev: str = ""
    forbidden: list[str] = field(default_factory=list)


@dataclass
class Place:
    official: str
    wrong: list[str] = field(default_factory=list)


@dataclass
class NameCheck:
    text: str
    findings: list[dict[str, Any]] = field(default_factory=list)

    @property
    def blocking(self) -> list[dict[str, Any]]:
        return [f for f in self.findings if f["type"] in ("UNVERIFIED_NAME", "TITLE_MISMATCH")]

    def as_dict(self) -> dict[str, Any]:
        return {"text": self.text, "findings": self.findings,
                "auto_fixed": [f for f in self.findings if f["type"].endswith("_FIXED")],
                "needs_review": self.blocking, "publishable": not self.blocking}


def _split_list(v: str | None) -> list[str]:
    return [x.strip() for x in re.split(r"[,;]", v or "") if x.strip()]


class NameIndex:
    def __init__(self, records: Iterable[dict[str, Any]]):
        self.persons: list[Person] = []
        self.orgs: list[Org] = []
        self.places: list[Place] = []
        self.region_words: set[str] = set()
        for r in records:
            if not r.get("verified"):
                continue
            kind, rec = r["kind"], r["record"]
            if kind == "person":
                self.persons.append(Person(rec["nama_lengkap_bergelar"], core_name(rec["nama_lengkap_bergelar"]),
                                           rec.get("jabatan_resmi", ""), rec.get("sebutan_berikutnya", ""),
                                           _split_list(rec.get("ejaan_salah"))))
            elif kind == "leader":
                self.persons.append(Person(rec["nama_lengkap_bergelar"], core_name(rec["nama_lengkap_bergelar"]),
                                           rec.get("jabatan", ""), rec.get("sebutan_berikutnya", "")))
            elif kind == "person_history":
                if rec.get("nama_lengkap_bergelar"):
                    self.persons.append(Person(rec["nama_lengkap_bergelar"], core_name(rec["nama_lengkap_bergelar"]),
                                               rec.get("jabatan_saat_itu", ""), current=False))
            elif kind in ("pemda", "opd"):
                pass  # dikumpulkan di bawah
            elif kind == "partner":
                self.orgs.append(Org(rec["nama_resmi"], rec.get("singkatan_resmi", ""), _split_list(rec.get("singkatan_dilarang"))))
            elif kind == "unit":
                self.orgs.append(Org(rec.get("nama_resmi_unit", ""), rec.get("singkatan", "")))
            elif kind == "place":
                self.places.append(Place(rec["nama_resmi"], _split_list(rec.get("ejaan_salah"))))
        for kind in ("pemda", "opd"):
            kv = {r["key"]: r["record"].get("nilai", "") for r in records if r["kind"] == kind and r.get("verified")}
            if kv.get("nama_resmi"):
                self.orgs.append(Org(kv["nama_resmi"], kv.get("singkatan_resmi", ""), _split_list(kv.get("singkatan_dilarang"))))
        for o in self.orgs:
            self.region_words |= _sig_tokens(o.official)
        for p in self.places:
            self.region_words |= _sig_tokens(p.official)

    def find_person(self, name: str) -> Person | None:
        c = _norm(core_name(name))
        for p in self.persons:
            if _norm(p.core) == c and p.current:
                return p
        for p in self.persons:
            if _norm(p.core) == c:
                return p
        return None

    def fuzzy_person(self, name: str, threshold: float = 0.86) -> Person | None:
        c = _norm(core_name(name))
        if len(c) < 5:
            return None
        best, score = None, 0.0
        for p in self.persons:
            pc = _norm(p.core)
            if not pc or pc[0] != c[0] or abs(len(pc.split()) - len(c.split())) > 0:
                continue
            s = SequenceMatcher(None, c, pc).ratio()
            if s > score:
                best, score = p, s
        return best if best and threshold <= score < 1.0 else None


def _replace_word(text: str, wrong: str, right: str) -> tuple[str, int]:
    rx = re.compile(rf"(?<![\w-]){re.escape(wrong)}(?![\w-])", re.I)
    return rx.subn(right, text)


def _looks_like_name(name: str, index: NameIndex) -> bool:
    core = core_name(name)
    toks = [t for t in re.findall(r"[A-Za-z'’\-]+", core)]
    if not toks or not any(len(t) >= 3 for t in toks):
        return False
    lowered = [t.lower() for t in toks]
    if all(t in STOP_WORDS or t in index.region_words for t in lowered):
        return False
    if lowered[0] in STOP_WORDS:
        return False
    return True


ROLE_WORDS = {"kepala", "wakil", "sekretaris", "plt", "plh", "ketua", "direktur", "camat", "lurah", "bupati",
              "gubernur", "wali", "kota", "asisten", "inspektur"}
STRUCTURE_WORDS = {"badan", "dinas", "bidang", "bagian", "subbagian", "subbidang", "seksi", "kantor", "unit",
                   "sekretariat", "inspektorat", "kecamatan", "uptd"}


def _words(s: str) -> list[str]:
    return [w for w in re.findall(r"[A-Za-z]+", s)]


def _acronym_ok(acr: str, text: str) -> bool:
    """'PSDM' cocok dengan '... Pengembangan Sumber Daya Manusia'."""
    initials = "".join(w[0].lower() for w in _words(text) if w.lower() not in {"dan", "the"})
    return acr.lower() in initials


def _expand(title: str, index: "NameIndex") -> str:
    out = title
    for o in index.orgs:
        if o.abbrev and o.official:
            for ab in {o.abbrev, o.abbrev.split()[-1]}:
                if ab.isupper() and len(ab) >= 2:
                    out = re.sub(rf"\b{re.escape(ab)}\b", o.official, out)
    return out


def _title_matches(found_title: str, person: Person, index: "NameIndex") -> bool:
    """Jabatan yang tertulis harus konsisten dengan jabatan resmi: kata peran, kata struktur, dan isi."""
    want_text = _expand(f"{person.title} {person.title_alt}", index)
    found_words = [w for w in _words(_expand(found_title, index))]
    if not found_words:
        return True
    want_low = {w.lower() for w in _words(want_text)}
    found_low = [w.lower() for w in found_words]
    # kata peran (kepala, sekretaris, ...) yang tertulis harus ada di jabatan resmi
    for w in found_low:
        if w in ROLE_WORDS and w not in want_low:
            return False
    # kata struktur (badan vs bidang) tidak boleh tertukar
    for w in found_low:
        if w in STRUCTURE_WORDS and w not in want_low:
            return False
    content = [w for w in found_words if w.lower() not in ROLE_WORDS | STRUCTURE_WORDS | {"dan", "the"}]
    if not content:
        return True
    hits = 0
    for w in content:
        if w.lower() in want_low or (w.isupper() and len(w) >= 2 and _acronym_ok(w, want_text)):
            hits += 1
    return hits / len(content) >= 0.6


def check_names(text: str, records: Iterable[dict[str, Any]], *, mark: bool = True) -> NameCheck:
    records = list(records)
    index = NameIndex(records)
    result = NameCheck(text)
    out = text

    # 1. ejaan salah tercatat
    for p in index.persons:
        for w in p.wrong:
            out, n = _replace_word(out, w, p.core)
            if n:
                result.findings.append({"type": "AUTO_FIXED", "kind": "person", "from": w, "to": p.core, "count": n})
    for pl in index.places:
        for w in pl.wrong:
            out, n = _replace_word(out, w, pl.official)
            if n:
                result.findings.append({"type": "AUTO_FIXED", "kind": "place", "from": w, "to": pl.official, "count": n})
    # 2. singkatan terlarang
    for o in index.orgs:
        for w in o.forbidden:
            if not o.abbrev:
                continue
            out, n = _replace_word(out, w, o.abbrev)
            if n:
                result.findings.append({"type": "ABBREV_FIXED", "kind": "org", "from": w, "to": o.abbrev, "count": n})

    # 3. nama di samping jabatan
    seen: set[tuple[str, str]] = set()
    spans: list[tuple[int, int, str, str]] = []  # (start, end, name, title)
    for rx in (PATTERN_COMMA, PATTERN_DIRECT, PATTERN_SELAKU):
        for m in rx.finditer(out):
            name = m.group("name").strip().rstrip(",")
            title = m.group("title").strip()
            if (name, title) in seen or not _looks_like_name(name, index):
                continue
            seen.add((name, title))
            spans.append((m.start("name"), m.start("name") + len(name), name, title))

    replacements: list[tuple[int, int, str]] = []
    for start, end, name, title in sorted(spans):
        person = index.find_person(name)
        if person is None:
            fz = index.fuzzy_person(name)
            if fz:
                replacements.append((start, end, fz.core))
                result.findings.append({"type": "FUZZY_FIXED", "kind": "person", "from": name, "to": fz.core,
                                        "title_in_text": title})
                person = fz
            else:
                result.findings.append({"type": "UNVERIFIED_NAME", "name": name, "title_in_text": title,
                                        "question": f'Di bahan ada "{name} — {title}". Belum ada di Direktori. '
                                                    "Apakah ejaan dan jabatannya sudah benar?"})
                if mark:
                    replacements.append((start, end, f"[{UNVERIFIED_MARK}: {name}]"))
                continue
        if not person.current:
            result.findings.append({"type": "TITLE_MISMATCH", "name": person.core, "title_in_text": title,
                                    "reason": f"{person.core} tercatat sebagai pejabat terdahulu ({person.title})."})
            if mark:
                replacements.append((start, end, f"[{TITLE_MARK}: {person.core}]"))
        elif not _title_matches(title, person, index):
            result.findings.append({"type": "TITLE_MISMATCH", "name": person.core, "title_in_text": title,
                                    "official_title": person.title,
                                    "reason": "Jabatan di teks tidak cocok dengan jabatan resmi di Direktori."})
            if mark:
                replacements.append((start, end, f"[{TITLE_MARK}: {person.core}]"))

    # terapkan dari belakang agar posisi tetap sah; buang tumpang tindih
    last_start = len(out) + 1
    for start, end, new in sorted(replacements, key=lambda r: r[0], reverse=True):
        if end > last_start:
            continue
        out = out[:start] + new + out[end:]
        last_start = start

    result.text = out
    return result


def blocking_markers(text: str) -> list[str]:
    return [m.strip("[") for m in BLOCKING_MARKERS if m in (text or "")]
