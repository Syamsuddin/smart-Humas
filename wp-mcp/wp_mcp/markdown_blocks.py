"""Konversi Markdown → markup blok Gutenberg.

Didukung: paragraf, heading (H1 diturunkan ke H2 karena H1 milik judul), daftar (bertingkat),
kutipan, tabel, garis pemisah, kode, gambar, galeri.

Gambar memakai skema media WordPress:  ![alt teks](wpmedia:123 "keterangan")
Galeri memakai fence:                  ```gallery
                                       123, 124, 125
                                       ```
HTML mentah di-escape (tidak dieksekusi) kecuali allow_html=True.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from markdown_it import MarkdownIt
from markdown_it.token import Token

MediaResolver = Callable[[int], dict[str, Any]]
_MEDIA = re.compile(r"^wpmedia:(\d+)$")


@dataclass
class ConversionResult:
    content: str
    media_ids: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    word_count: int = 0


def _comment(name: str, attrs: dict | None = None) -> str:
    return f"<!-- wp:{name}{' ' + json.dumps(attrs, ensure_ascii=False, separators=(',', ':')) if attrs else ''} -->"


def _block(name: str, inner: str, attrs: dict | None = None) -> str:
    return f"{_comment(name, attrs)}\n{inner}\n<!-- /wp:{name} -->"


class GutenbergConverter:
    def __init__(self, resolve_media: MediaResolver | None = None, allow_html: bool = False):
        self.md = MarkdownIt("commonmark", {"html": allow_html, "linkify": False, "typographer": False}).enable("table")
        self.resolve_media = resolve_media or (lambda mid: {"url": "", "alt": ""})
        self.result = ConversionResult("")

    # --- publik -----------------------------------------------------------
    def convert(self, markdown: str) -> ConversionResult:
        self.result = ConversionResult("")
        tokens = self.md.parse(markdown or "")
        blocks = self._render_seq(tokens)
        self.result.content = "\n\n".join(b for b in blocks if b)
        self.result.word_count = len(re.findall(r"\w+", re.sub(r"<[^>]+>|<!--.*?-->", " ", self.result.content)))
        return self.result

    # --- traversal --------------------------------------------------------
    @staticmethod
    def _split(tokens: list[Token]) -> list[list[Token]]:
        """Pisahkan deret token menjadi blok tingkat atas (pasangan open/close)."""
        groups: list[list[Token]] = []
        i = 0
        while i < len(tokens):
            t = tokens[i]
            if t.nesting == 1:
                depth, j = 0, i
                while j < len(tokens):
                    depth += tokens[j].nesting
                    if depth == 0:
                        break
                    j += 1
                groups.append(tokens[i: j + 1])
                i = j + 1
            else:
                groups.append([t])
                i += 1
        return groups

    def _render_seq(self, tokens: list[Token]) -> list[str]:
        return [self._render_group(g) for g in self._split(tokens)]

    def _inline(self, tok: Token) -> str:
        """Render inline; gambar di tengah teks dibuang (hanya alt-nya tersisa) agar tidak ada sumber luar
        seperti piksel pelacak atau gambar yang bisa ditukar setelah disetujui."""
        children: list[Token] = []
        for child in tok.children or []:
            if child.type == "image":
                src = child.attrGet("src") or ""
                alt = "".join(c.content for c in (child.children or [])) or child.content
                self.result.warnings.append(
                    f"Gambar '{src[:60]}' di tengah paragraf dibuang; taruh gambar wpmedia:ID di paragrafnya sendiri.")
                t = Token("text", "", 0)
                t.content = alt
                children.append(t)
            else:
                children.append(child)
        return self.md.renderer.renderInline(children, self.md.options, {})

    def _render_group(self, g: list[Token]) -> str:
        t = g[0]
        kind = t.type
        if kind == "paragraph_open":
            inline = g[1]
            image = self._lone_image(inline)
            if image:
                return image
            return _block("paragraph", f"<p>{self._inline(inline)}</p>")
        if kind == "heading_open":
            level = int(t.tag[1])
            if level == 1:
                self.result.warnings.append("Heading H1 diturunkan ke H2; H1 dipakai judul berita.")
                level = 2
            attrs = None if level == 2 else {"level": level}
            return _block("heading", f'<h{level} class="wp-block-heading">{self._inline(g[1])}</h{level}>', attrs)
        if kind in ("bullet_list_open", "ordered_list_open"):
            return self._list(g)
        if kind == "blockquote_open":
            inner = "".join(self._render_seq(g[1:-1]))
            return _block("quote", f'<blockquote class="wp-block-quote">{inner}</blockquote>')
        if kind == "table_open":
            table = self.md.renderer.render(g, self.md.options, {})
            table = table.replace("<table>", '<table class="has-fixed-layout">', 1)
            return _block("table", f'<figure class="wp-block-table">{table.strip()}</figure>')
        if kind == "hr":
            return _block("separator", '<hr class="wp-block-separator has-alpha-channel-opacity"/>')
        if kind in ("fence", "code_block"):
            if kind == "fence" and t.info.strip().lower() == "gallery":
                return self._gallery(t.content)
            return _block("code", f'<pre class="wp-block-code"><code>{html.escape(t.content.rstrip())}</code></pre>')
        if kind == "html_block":
            return _block("html", t.content.strip())
        # token lain (mis. inline sisa) dirender apa adanya
        return self.md.renderer.render(g, self.md.options, {}).strip()

    def _list(self, g: list[Token]) -> str:
        ordered = g[0].type == "ordered_list_open"
        tag = "ol" if ordered else "ul"
        items: list[str] = []
        for item in self._split(g[1:-1]):
            if item[0].type != "list_item_open":
                continue
            parts: list[str] = []
            for sub in self._split(item[1:-1]):
                if sub[0].type == "paragraph_open":
                    parts.append(self._inline(sub[1]))
                elif sub[0].type in ("bullet_list_open", "ordered_list_open"):
                    parts.append(self._list(sub))
                else:
                    parts.append(self._render_group(sub))
            items.append(_block("list-item", f"<li>{''.join(parts)}</li>"))
        attrs = {"ordered": True} if ordered else None
        start = g[0].attrGet("start")
        if ordered and start and str(start) != "1":
            attrs = {"ordered": True, "start": int(start)}
        start_attr = f' start="{int(start)}"' if ordered and start and str(start) != "1" else ""
        return _block("list", f'<{tag}{start_attr} class="wp-block-list">' + "".join(items) + f"</{tag}>", attrs)

    # --- media ------------------------------------------------------------
    def _lone_image(self, inline: Token) -> str | None:
        kids = [c for c in (inline.children or []) if not (c.type == "text" and not c.content.strip())]
        if len(kids) != 1 or kids[0].type != "image":
            return None
        img = kids[0]
        src = img.attrGet("src") or ""
        m = _MEDIA.match(src)
        alt = "".join(c.content for c in (img.children or [])) or img.content
        caption = img.attrGet("title") or ""
        if not m:
            self.result.warnings.append(f"Gambar dengan sumber luar '{src[:60]}' tidak diizinkan; unggah dulu dengan upload_media.")
            return None
        return self._image_block(int(m.group(1)), alt, caption)

    def _image_block(self, media_id: int, alt: str = "", caption: str = "") -> str:
        info = self.resolve_media(media_id) or {}
        if media_id not in self.result.media_ids:
            self.result.media_ids.append(media_id)
        url = info.get("url", "")
        alt = alt or info.get("alt", "")
        if not alt:
            self.result.warnings.append(f"Media {media_id} tanpa alt text.")
        cap = f'<figcaption class="wp-element-caption">{html.escape(caption)}</figcaption>' if caption else ""
        inner = (f'<figure class="wp-block-image size-large"><img src="{html.escape(url, quote=True)}" '
                 f'alt="{html.escape(alt, quote=True)}" class="wp-image-{media_id}"/>{cap}</figure>')
        return _block("image", inner, {"id": media_id, "sizeSlug": "large", "linkDestination": "none"})

    def _gallery(self, body: str) -> str:
        ids = [int(x) for x in re.findall(r"\d+", body)]
        if not ids:
            self.result.warnings.append("Blok galeri kosong diabaikan.")
            return ""
        images = "\n\n".join(self._image_block(i) for i in ids)
        return _block("gallery", f'<figure class="wp-block-gallery has-nested-images columns-default is-cropped">\n{images}\n</figure>',
                      {"linkTo": "none"})


def markdown_to_blocks(markdown: str, resolve_media: MediaResolver | None = None, allow_html: bool = False) -> ConversionResult:
    return GutenbergConverter(resolve_media, allow_html).convert(markdown)


def plain_text(content: str) -> str:
    """Teks polos dari HTML/blok, untuk pemeriksa nama dan data pribadi."""
    txt = re.sub(r"<!--.*?-->", " ", content or "", flags=re.S)
    txt = re.sub(r"<[^>]+>", " ", txt)
    return re.sub(r"\s+", " ", html.unescape(txt)).strip()
