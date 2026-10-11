"""Pengolahan foto berita: ukuran per peran, crop cerdas, WebP, buang EXIF (termasuk lokasi).

Peran (lihat config media.*):
  featured  1200×675 (16:9) crop ke wajah/objek utama
  inline    lebar 1024, rasio asli
  gallery   lebar 800, rasio asli
  social    1080×1080 (1:1)
"""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Any

from PIL import Image, ImageOps

from .errors import InvalidInput

try:  # opsional: deteksi wajah untuk crop
    import cv2  # type: ignore
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover - tergantung lingkungan
    cv2 = None
    np = None


@dataclass
class ProcessedImage:
    data: bytes
    width: int
    height: int
    format: str
    quality: int
    bytes_size: int
    crop_strategy: str
    exif_removed: bool


def slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:max_len].strip("-") or "foto"


def media_filename(title: str, index: int, ext: str = "webp", day: date | None = None) -> str:
    return f"{(day or date.today()).isoformat()}-{slugify(title, 50)}-{index:02d}.{ext}"


def _faces_center(img: Image.Image) -> tuple[float, float] | None:
    if cv2 is None:
        return None
    try:
        arr = np.array(img.convert("L"))
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        faces = cascade.detectMultiScale(arr, scaleFactor=1.1, minNeighbors=5, minSize=(24, 24))
    except Exception:
        return None
    if len(faces) == 0:
        return None
    xs = [x + w / 2 for (x, y, w, h) in faces]
    ys = [y + h / 2 for (x, y, w, h) in faces]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _crop_to_ratio(img: Image.Image, ratio: float) -> tuple[Image.Image, str]:
    w, h = img.size
    if abs(w / h - ratio) < 0.01:
        return img, "none"
    center = _faces_center(img)
    strategy = "faces" if center else "center"
    cx, cy = center or (w / 2, h / 2)
    if w / h > ratio:  # terlalu lebar → potong sisi
        nw = int(h * ratio)
        left = int(min(max(cx - nw / 2, 0), w - nw))
        return img.crop((left, 0, left + nw, h)), strategy
    nh = int(w / ratio)
    # wajah biasanya di sepertiga atas; geser sedikit agar kepala tidak terpotong
    top = int(min(max(cy - nh * 0.4, 0), h - nh))
    return img.crop((0, top, w, top + nh)), strategy


def process_image(raw: bytes, role: str, spec: dict[str, Any]) -> ProcessedImage:
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as exc:
        raise InvalidInput(f"Berkas bukan gambar yang bisa dibaca: {exc}") from None
    img = ImageOps.exif_transpose(img)  # hormati orientasi kamera, lalu EXIF dibuang saat simpan
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")

    strategy = "none"
    tw, th = int(spec["width"]), spec.get("height")
    if th:
        img, strategy = _crop_to_ratio(img, tw / int(th))
        img = img.resize((tw, int(th)), Image.LANCZOS) if img.size != (tw, int(th)) else img
    elif img.width > tw:
        img = img.resize((tw, round(img.height * tw / img.width)), Image.LANCZOS)

    fmt = "WEBP"
    quality = int(spec.get("quality", 80))
    max_bytes = int(spec.get("max_kb", 300)) * 1024
    data = b""
    for q in range(quality, 39, -6):
        buf = io.BytesIO()
        img.save(buf, fmt, quality=q, method=6)  # tanpa exif=..., metadata tidak ikut tersimpan
        data, quality = buf.getvalue(), q
        if len(data) <= max_bytes:
            break
    return ProcessedImage(data, img.width, img.height, fmt.lower(), quality, len(data), strategy, True)
