<p align="center">
  <img src="docs/assets/header.jpg" alt="Smart-Humas — WP-MCP untuk website humas pemerintah daerah" width="100%">
</p>

# Smart Humas — WP-MCP untuk website humas pemerintah daerah

Claude sebagai **operator redaksi** website WordPress humas setda dan OPD, dengan hierarki tiga peran:

| Peran | Siapa | Wewenang |
|---|---|---|
| `operator-ai` | Claude | menyusun dan merevisi draft, mengolah foto, menyiapkan balasan komentar |
| `admin-web` | pengelola website | memerintahkan perbaikan, mengajukan ke pimpinan, menyetujui balasan rutin |
| `pimpinan` | kepala OPD / pejabat yang ditunjuk | review akhir, suntingan kecil, setujui dan terbitkan, delegasi |

Alur: **draft → revisi → siap_tayang (terkunci) → published**, dengan ralat terbuka dan pencabutan beralasan
(praktik Pedoman Pemberitaan Media Siber). Gaya bahasa diturunkan dari Permen PANRB 82/2012 dan EYD Edisi V;
nama pejabat dan OPD hanya dari **Direktori Redaksi** yang disahkan admin, diperiksa mesin di setiap draft.

## Isi repo

| Folder | Isi | Lisensi |
|---|---|---|
| [`wp-mcp/`](wp-mcp) | Server MCP (Python, SDK `mcp` 2.x): 48 tool, lapisan kebijakan, pemeriksa nama, pemasker data pribadi, Memori Redaksi, Direktori, pengolah foto, uji | Komersial |
| [`wp-mcp-bridge/`](wp-mcp-bridge) | Plugin WordPress tipis: peran Editor AI, meta alur kerja, akun AI hanya dari server sendiri, halaman **Persetujuan WP-MCP** | GPL-2.0+ |
| [`wp-mcp-opd/`](wp-mcp-opd) | Plugin Claude Code: skill `/berita`, `/balas-komentar`, `/halaman`, `/siapkan-direktori` | Komersial |
| [`deploy/`](deploy) | `install.sh`, launcher SSH (`wp-mcp-launch`, termasuk mode unggah foto), pembungkus sudo `wp-safe` | Komersial |
| [`docs/`](docs) | Templat Direktori Redaksi, protokol wawancara, model keamanan | — |

## Pasang (ringkas)

Di VPS Ubuntu tempat WordPress berjalan:

```bash
git clone https://github.com/Syamsuddin/smart-humas && cd smart-humas
sudo ./deploy/install.sh --wp-path /var/www/html --site-url https://humas.contoh.go.id
sudo nano /etc/wp-mcp/actors.yaml          # admin-web & pimpinan, telegram_user_id, wp_user
sudo nano /var/lib/wp-mcp/.ssh/authorized_keys   # satu baris per orang, lihat deploy/authorized_keys.example
sudo -u wpmcp WPMCP_CONFIG_DIR=/etc/wp-mcp /opt/wp-mcp/venv/bin/wp-mcp check
```

Di laptop admin/pimpinan: lihat [`wp-mcp-opd/README.md`](wp-mcp-opd/README.md) (`WPMCP_SSH_TARGET`, pasang
plugin dari marketplace repo ini, salin aturan izin), lalu jalankan `/siapkan-direktori`.

## Model keamanan (inti)

Rincian lengkap di [`docs/KEAMANAN.md`](docs/KEAMANAN.md).

- Semua aturan ditegakkan di satu tempat (`wp_mcp/policy.py`); tool sendiri tidak memeriksa izin.
- **Pintu model** (Claude Code dan pintu lain yang digerakkan model bahasa): setiap pengajuan, penerbitan,
  pengiriman balasan, perubahan Direktori, atau aksi sistem menjadi *aksi tertunda* yang hanya sah dengan
  persetujuan **di luar percakapan**: kode yang dikirim ke Telegram manusia lalu diketik sendiri, atau tombol
  Setujui di wp-admin → Persetujuan WP-MCP. Model tidak bisa mengonfirmasi dirinya sendiri, dan instruksi di
  dalam bahan (caption, PDF, komentar) tidak bisa memicu penerbitan.
- Aktor ditentukan kunci SSH (forced command), bukan klien. Akun WordPress AI berperan Editor AI, ditolak bila
  tidak datang dari server sendiri (IP loopback + header rahasia), tidak bisa XML-RPC atau login wp-admin.
- WP-CLI hanya lewat `wp-safe` milik root (whitelist di balik sudo, lingkungan bersih).
- Data pribadi (NIK, HP, email non-dinas, NPWP, rekening) diblokir sebelum ditulis; identitas komentator di-hash;
  foto dipindai OCR lokal untuk dokumen identitas; EXIF/lokasi dibuang. Log audit append-only, data pribadi dimasker.

## Uji

```bash
cd wp-mcp && pip install -e '.[dev]' && python -m pytest -q     # 55 uji, termasuk MCP stdio ujung-ke-ujung
php -l ../wp-mcp-bridge/wp-mcp-bridge.php
claude plugin validate .. --strict && claude plugin validate ../wp-mcp-opd --strict
```

Uji memakai WordPress palsu berbasis HTTP (`tests/fake_wp.py`) dan WP-CLI palsu. **Belum** diuji terhadap
WordPress sungguhan; lakukan di staging sebelum produksi (lihat bagian *Status* di bawah).

## Status

Fase 0–1 (fondasi, alur konten tiga peran, Direktori, Memori Redaksi, komentar, media) selesai dan teruji di
lingkungan tiruan. Belum: gateway Telegram dengan tombol, `wp-mcp-voice-api` + aplikasi mWPAdmin, audit situs
massal, tema-sebagai-kode (Fase 2–3 dosir).

Penulis: Syamsuddin Ideris (syamsuddin.ideris@gmail.com).
