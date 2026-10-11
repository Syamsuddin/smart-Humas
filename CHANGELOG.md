# Changelog

Semua perubahan penting pada Smart-Humas dicatat di berkas ini.

Format mengikuti [Keep a Changelog](https://keepachangelog.com/id-ID/1.1.0/),
dan penomoran versi mengikuti [Semantic Versioning](https://semver.org/lang/id/).

## [0.1.0] - 2026-10-11

Rilis awal: Fase 0–1 WP-MCP untuk website humas pemerintah daerah, dengan
hierarki operator-ai → admin-web → pimpinan.

### Ditambahkan

- **wp-mcp** — server MCP WordPress dengan 48 tool: konten dan alur
  persetujuan, media, komentar, taksonomi, Direktori Redaksi, Memori Redaksi,
  delegasi, konfirmasi, dan konteks redaksi.
- Dispatcher kebijakan tunggal, dengan persetujuan di luar percakapan untuk
  pintu model (kode Telegram / wp-admin).
- Pemeriksa nama pejabat dan OPD, serta pemasker data pribadi.
- Konversi Markdown ke Gutenberg dan pengolah foto (WebP, crop, buang EXIF).
- Adaptor cache dan keamanan, serta log audit append-only.
- **wp-mcp-bridge** (GPL) — plugin WordPress dengan peran Editor AI, meta
  alur kerja, dan halaman Persetujuan WP-MCP. Akun AI hanya diterima dari
  server sendiri (loopback dan header rahasia, tanpa XML-RPC).
- **wp-mcp-opd** — plugin Claude Code dengan skill `/berita`,
  `/balas-komentar`, `/halaman`, dan `/siapkan-direktori`, serta marketplace
  repo.
- **deploy** — `install.sh`, launcher SSH (stdio dan unggah foto), dan
  `wp-safe` (whitelist WP-CLI di balik sudo).
- Dokumentasi: README (instalasi server dan laptop, Direktori, uji,
  pembaruan, pemecahan masalah), simulasi alur penggunaan, `docs/KEAMANAN.md`,
  dan gambar header.
- 55 uji untuk wp-mcp, termasuk uji regresi `tests/test_model_door.py`.

### Keamanan

- Dua putaran tinjauan keamanan independen. Seluruh temuan sudah diperbaiki
  dan punya uji regresi.

### Diperbaiki

- Perintah pemasangan plugin Claude Code (marketplace add dan install
  `plugin@marketplace`).

[0.1.0]: https://github.com/Syamsuddin/smart-Humas/releases/tag/v0.1.0
