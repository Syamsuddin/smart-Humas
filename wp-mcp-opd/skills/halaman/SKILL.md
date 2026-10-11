---
name: halaman
description: Menyusun draft halaman statis website humas pemerintah daerah lewat WP-MCP — halaman layanan publik (syarat, alur, biaya, waktu, kontak, dasar hukum), profil OPD, program, pengumuman, dan informasi publik PPID — dari dokumen sumber (Perbup, SK, SOP), diperiksa ulang oleh pemeriksa independen. Pakai saat pengguna minta "buat halaman", "halaman layanan untuk ...", "ubah Perbup ini jadi halaman", "profil OPD", atau "halaman PPID".
---

# /halaman — Drafter halaman statis

Halaman bertahan lama dan sering dirujuk warga, jadi setiap angka harus tertelusur ke sumber.

## Langkah

1. `get_editorial_context(purpose="halaman")`.
2. Tentukan jenis dan baca strukturnya di [templat-halaman.md](templat-halaman.md).
3. Ekstrak isi per bagian wajib dari dokumen sumber. Yang tidak ada ditulis `[BELUM ADA DI SUMBER: ...]`.
   Tidak ada biaya, waktu, atau syarat yang ditulis tanpa sumber.
4. Tulis dari sudut pandang warga ("Anda membawa", bukan "pemohon menyerahkan"); alur sebagai daftar
   bernomor; biaya dan waktu dalam tabel; blok "Dasar hukum" dengan nomor dan judul persis seperti sumber;
   blok "Terakhir diperbarui" dan "Sumber" di bawah.
5. Satu halaman untuk satu layanan. Bila sumber memuat beberapa layanan, usulkan beberapa halaman + satu halaman induk.
6. `verify_names(text)` lalu `create_draft(type="page", title, content_markdown, source_note)`.
7. **Pemeriksa independen**: jalankan subagent baru dengan instruksi di [pemeriksa.md](pemeriksa.md),
   beri hanya teks halaman jadi dan teks dokumen sumber (bukan proses penyusunanmu).
   Masukkan hasilnya sebagai `note` saat admin-web mengajukan (`submit_to_leader`) dan laporkan ke pengguna.
8. Laporan: tautan edit, daftar `[BELUM ADA DI SUMBER]`, hasil pemeriksa (cocok/tidak per angka), usulan letak di menu.

Pengajuan, suntingan pimpinan, dan persetujuan mengikuti alur yang sama dengan /berita:
`submit_to_leader` (admin-web) → `leader_edit` / `approve_and_publish` (pimpinan). Setiap aksi itu menjadi
`pending_action`: bacakan readback, minta pengguna mengetik kode dari Telegram atau menyetujui di wp-admin →
Persetujuan WP-MCP, baru `confirm_action`. Jangan pernah menebak kode.
