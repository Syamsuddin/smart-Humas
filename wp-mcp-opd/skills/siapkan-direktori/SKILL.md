---
name: siapkan-direktori
description: Melengkapi Direktori Redaksi WP-MCP (nama resmi pemda dan OPD, singkatan resmi dan terlarang, pimpinan daerah, unit kerja, pejabat struktural, tempat, program, kategori, admin redaksi) lewat wawancara singkat dengan admin-web, maksimal lima pertanyaan per putaran, tanpa pernah mengarang nama atau gelar. Pakai saat instalasi baru, saat pengguna minta "siapkan direktori", "isi data pejabat", "ada pejabat baru/mutasi", "perbarui nama OPD", atau saat skill lain melaporkan Direktori belum lengkap.
---

# /siapkan-direktori — Wawancara pengisian Direktori Redaksi

Ikuti protokol lengkap di [wawancara-direktori.md](wawancara-direktori.md). Ringkasnya:

1. `directory_status()` → bidang wajib yang kosong (`missing`) dan belum disahkan (`unverified`),
   sudah urut prioritas B → D → C → A → A.1 → I → H.1. Jangan menanyakan yang sudah terisi.
2. Putaran pertama selalu tawarkan jalan pintas: tempel tabel Excel/ekspor SIMPEG, foto bagan
   struktur atau SK, atau PDF Perbup SOTK. Satu tempelan menggantikan puluhan pertanyaan.
3. Tanpa dokumen: maksimal 5 pertanyaan per putaran, dikelompokkan per bagian.
4. Setiap jawaban diulang balik sebagai tabel yang akan disimpan. Setelah pengguna membalas **sah**, simpan.
   Karena tiap penyimpanan Direktori dari Claude Code butuh persetujuan di luar percakapan (kode Telegram atau
   wp-admin → Persetujuan WP-MCP), **kumpulkan dulu** jawaban satu putaran, lalu simpan sekaligus dengan
   `directory_import(markdown=<potongan berformat templat>)` — satu persetujuan untuk banyak baris.
   `directory_set` hanya untuk satu rekaman (mis. konfirmasi nama dari wawancara mini).
   Bacakan `readback` (jumlah per jenis, daftar pejabat) sebelum pengguna menyetujui; jangan pernah menebak kode.
5. Ulangi sampai `status = lengkap-wajib`. Tawarkan bagian opsional (E, F, G, H) sekali saja.
6. Tutup dengan uji cepat: ambil 3 berita lama (`list_posts(state="published", limit=3)` lalu `get_post`)
   dan jalankan `verify_names` atas teksnya; pejabat OPD tidak boleh muncul sebagai "tidak dikenal".

## Bentuk record per jenis

| kind | kunci | bidang lain |
|---|---|---|
| pemda, opd | `bidang` | `nilai` (satu rekaman per bidang: nama_resmi, singkatan_resmi, singkatan_dilarang, ...) |
| leader | `jabatan` | nama_lengkap_bergelar, sebutan_pertama, sebutan_berikutnya, sejak |
| unit | `kode` | nama_resmi_unit, singkatan, induk |
| person | `kode` | nama_lengkap_bergelar, jabatan_resmi, unit, sebutan_berikutnya, sejak, ejaan_salah |
| place | `nama_resmi` | ejaan_salah, jenis, kecamatan |
| program | `nama_program` | singkatan, tujuan_satu_kalimat, dasar_hukum, url_halaman, tag_baku |
| style | `aturan` | contoh_benar, contoh_salah |
| category | `jenis_berita` | kategori_wordpress (harus kategori yang sudah ada: cek `list_terms`), tag_wajib |
| editor | `peran` | nama, kanal |

## Mutasi pejabat

"Kepala Bidang X sekarang [nama]" → `directory_retire_person(kode, sampai, digantikan_oleh)` untuk
pejabat lama, lalu `directory_set(kind="person", ...)` untuk pejabat baru setelah diulang balik dan disahkan.

## Larangan

Tidak menanyakan atau menyimpan NIP, nomor HP pribadi, alamat rumah. Tidak mengisi nama dari ingatan
model atau pencarian web, sekalipun "kelihatannya" benar. operator-ai tidak bisa menyimpan; sesi
harus dijalankan admin-web atau pimpinan, dan persetujuannya selalu dari manusia di luar percakapan.
