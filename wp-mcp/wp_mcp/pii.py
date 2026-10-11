"""Pemeriksa dan pemasker data pribadi.

Penyaringan terjadi di WP-MCP, bukan di skill atau gateway, sehingga tidak bisa
dilewati lewat prompt. Pola dibaca dari pii_patterns.yaml.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Finding:
    pattern: str
    label: str
    start: int
    end: int
    masked: str

    def as_dict(self, field: str | None = None) -> dict[str, Any]:
        d = {"code": "PII_DETECTED", "pattern": self.pattern, "label": self.label,
             "position": self.start, "sample": self.masked}
        if field:
            d["field"] = field
        return d


def _valid_nik(digits: str) -> bool:
    """NIK/KK: kode provinsi 11-94, tanggal 01-31 (atau 41-71 untuk perempuan), bulan 01-12."""
    if len(digits) != 16 or not digits.isdigit():
        return False
    prov = int(digits[0:2])
    day = int(digits[6:8])
    month = int(digits[8:10])
    if not 11 <= prov <= 94:
        return False
    if not (1 <= day <= 31 or 41 <= day <= 71):
        return False
    return 1 <= month <= 12


def _mask(value: str) -> str:
    v = value.strip()
    if len(v) <= 4:
        return "*" * len(v)
    return v[:2] + "*" * (len(v) - 4) + v[-2:]


class PIIScanner:
    def __init__(self, spec: dict[str, Any]):
        self.patterns: list[tuple[str, dict[str, Any], re.Pattern[str]]] = []
        for name, p in (spec.get("patterns") or {}).items():
            self.patterns.append((name, p, re.compile(p["regex"])))
        self.ocr_keywords = [k.upper() for k in spec.get("ocr_keywords", [])]

    def scan(self, text: str | None) -> list[Finding]:
        if not text:
            return []
        found: list[Finding] = []
        for name, spec, rx in self.patterns:
            for m in rx.finditer(text):
                value = m.group(1) if m.groups() else m.group(0)
                if spec.get("validator") == "nik" and not _valid_nik(re.sub(r"\D", "", value)):
                    continue
                if any(value.lower().endswith(s) for s in spec.get("allow_suffixes", [])):
                    continue
                found.append(Finding(name, spec.get("label", name), m.start(), m.end(), _mask(value)))
        return found

    def mask(self, text: str | None) -> str | None:
        if not text:
            return text
        out = text
        for f in sorted(self.scan(text), key=lambda f: f.start, reverse=True):
            out = out[: f.start] + f"[{f.label} disamarkan]" + out[f.end:]
        return out

    # --- gambar -----------------------------------------------------------
    def ocr_image(self, path: str | Path) -> str:
        exe = shutil.which("tesseract")
        if not exe:
            return ""
        langs = "ind+eng" if _has_lang(exe, "ind") else "eng"
        try:
            proc = subprocess.run([exe, str(path), "stdout", "-l", langs], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return proc.stdout or ""

    def scan_image(self, path: str | Path) -> dict[str, Any]:
        """Kembalikan temuan dokumen identitas pada gambar (OCR lokal, tidak dikirim keluar)."""
        text = self.ocr_image(path)
        upper = text.upper()
        keywords = [k for k in self.ocr_keywords if k in upper]
        findings = [f.as_dict("image_text") for f in self.scan(text)]
        suspicious = bool(findings) or len(keywords) >= 2
        return {"ocr_available": bool(shutil.which("tesseract")), "suspicious": suspicious,
                "keywords": keywords, "findings": findings}


_LANG_CACHE: dict[str, bool] = {}


def _has_lang(exe: str, lang: str) -> bool:
    if lang not in _LANG_CACHE:
        try:
            out = subprocess.run([exe, "--list-langs"], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.TimeoutExpired):
            out = ""
        _LANG_CACHE[lang] = lang in out.split()
    return _LANG_CACHE[lang]


def hash_identity(value: str | None, salt: str = "wp-mcp") -> str | None:
    """Hash satu arah untuk email/IP komentator agar bisa dikelompokkan tanpa dibuka."""
    if not value:
        return value
    return "h:" + hashlib.sha256((salt + value).encode()).hexdigest()[:12]
