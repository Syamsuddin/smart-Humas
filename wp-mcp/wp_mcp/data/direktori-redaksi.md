---
dosir: direktori-redaksi
versi_skema: 1.0
situs_url: "[KOSONG]"
opd_pemilik: "[KOSONG]"
pemda: "[KOSONG]"
diperbarui: "[KOSONG]"          # YYYY-MM-DD
disahkan_oleh: "[KOSONG]"       # nama Admin website
status: draft                   # draft | lengkap-wajib | lengkap
---

# Direktori Redaksi Website Humas

Sumber kebenaran tunggal untuk nama pemda, OPD, unit, jabatan, pejabat, tempat, dan program
yang dipakai skill `/berita`, `/balas-komentar`, dan `/halaman`.
Diimpor ke WP-MCP dengan `directory_import`; setiap draft diperiksa terhadapnya oleh `verify_names`.

## Aturan pengisian

- Tulis persis seperti di dokumen resmi (SK, Perbup SOTK, papan nama). Jangan menebak gelar.
- `[WAJIB]` harus terisi sebelum `status: lengkap-wajib`. `[OPSIONAL]` boleh kosong.
- Isian kosong ditulis `[KOSONG]`. Jangan dihapus barisnya.
- Kolom `sumber` diisi asal data: `SK`, `Perbup`, `papan-nama`, `admin`, `website-lama`.
- Kolom `verif` diisi `ya` hanya setelah Admin mengesahkan. Entri `verif: tidak` tidak dipakai menulis.
- Hanya informasi publik. Tidak ada NIP, nomor HP pribadi, alamat rumah, atau data warga.

---

## A. Identitas pemerintah daerah

| Bidang | Nilai | Keterangan | Wajib |
|---|---|---|---|
| nama_resmi | [KOSONG] | contoh: Pemerintah Kabupaten Contoh (atau Pemerintah Kota ...) | WAJIB |
| singkatan_resmi | [KOSONG] | contoh: Pemkab Contoh | WAJIB |
| singkatan_dilarang | [KOSONG] | dipisah koma | OPSIONAL |
| ibu_kota | [KOSONG] | untuk baris tanggal-tempat berita | WAJIB |
| format_dateline | [KOSONG] | contoh: `KOTA BARU -` (nama ibu kota, huruf kapital) | WAJIB |

### A.1 Pimpinan daerah

| jabatan | nama_lengkap_bergelar | sebutan_pertama | sebutan_berikutnya | sejak | sumber | verif |
|---|---|---|---|---|---|---|
| Bupati | [KOSONG] | [KOSONG] | [KOSONG] | [KOSONG] | | tidak |
| Wakil Bupati | [KOSONG] | [KOSONG] | [KOSONG] | [KOSONG] | | tidak |
| Sekretaris Daerah | [KOSONG] | [KOSONG] | [KOSONG] | [KOSONG] | | tidak |

`sebutan_pertama` contoh: "Bupati Contoh, [nama lengkap bergelar]" (untuk kota: Wali Kota).
`sebutan_berikutnya` contoh: "Bupati [nama panggilan resmi]" atau "Bupati".

---

## B. OPD pemilik website `[WAJIB]`

| Bidang | Nilai | Wajib |
|---|---|---|
| nama_resmi | [KOSONG] | WAJIB |
| singkatan_resmi | [KOSONG] | WAJIB |
| singkatan_dilarang | [KOSONG] | OPSIONAL |
| dasar_hukum_sotk | [KOSONG] | OPSIONAL |
| alamat_kantor | [KOSONG] | WAJIB |
| telepon_kantor | [KOSONG] | OPSIONAL |
| email_resmi | [KOSONG] | OPSIONAL |
| jam_layanan | [KOSONG] | OPSIONAL |
| url_profil | [KOSONG] | OPSIONAL |
| kredit_foto | [KOSONG] | WAJIB — contoh: `(Foto: Humas Setda Contoh)` |
| penanda_sumber_berita | [KOSONG] | WAJIB — contoh: `(Humas Setda Contoh)` |

---

## C. Unit kerja di dalam OPD `[WAJIB]`

| kode | nama_resmi_unit | singkatan | induk | sumber | verif |
|---|---|---|---|---|---|
| U01 | [KOSONG] | [KOSONG] | (OPD) | | tidak |
| U02 | [KOSONG] | [KOSONG] | (OPD) | | tidak |
| U03 | [KOSONG] | [KOSONG] | (OPD) | | tidak |

Contoh baris: `U02 | Bidang Pengembangan Sumber Daya Manusia | Bidang PSDM | (OPD)`.
Sub-bagian atau subbidang ditulis dengan `induk` = kode unit di atasnya.

---

## D. Pejabat struktural `[WAJIB]`

| kode | nama_lengkap_bergelar | jabatan_resmi | unit | sebutan_berikutnya | sejak | ejaan_salah | sumber | verif |
|---|---|---|---|---|---|---|---|---|
| P01 | [KOSONG] | Kepala [nama OPD] | (OPD) | [KOSONG] | [KOSONG] | | | tidak |
| P02 | [KOSONG] | Sekretaris | (OPD) | [KOSONG] | [KOSONG] | | | tidak |
| P03 | [KOSONG] | Kepala Bidang [..] | U02 | [KOSONG] | [KOSONG] | | | tidak |

- `jabatan_resmi` ditulis lengkap tanpa singkatan.
- `sebutan_berikutnya` contoh: "Kepala Bidang PSDM" atau "Kabid PSDM" (sesuai kebiasaan OPD).
- `ejaan_salah` diisi varian yang pernah muncul (dipisah koma), agar terdeteksi otomatis.
- Pejabat yang sudah pindah tidak dihapus: pindahkan ke D.1.

### D.1 Riwayat pejabat

| kode | nama_lengkap_bergelar | jabatan_saat_itu | sampai | digantikan_oleh |
|---|---|---|---|---|

---

## E. OPD dan instansi mitra yang sering disebut `[OPSIONAL]`

| nama_resmi | singkatan_resmi | singkatan_dilarang | pimpinan_bergelar | jabatan_pimpinan | verif |
|---|---|---|---|---|---|

---

## F. Tempat yang sering disebut `[OPSIONAL]`

| nama_resmi | ejaan_salah | jenis | kecamatan | verif |
|---|---|---|---|---|

`jenis`: aula, kantor, gedung, desa, kecamatan, objek wisata.

---

## G. Program dan kegiatan rutin `[OPSIONAL]`

| nama_program | singkatan | tujuan_satu_kalimat | dasar_hukum | url_halaman | tag_baku | berlaku_sampai |
|---|---|---|---|---|---|---|

---

## H. Gaya redaksi khusus OPD `[OPSIONAL]`

| aturan | contoh_benar | contoh_salah |
|---|---|---|
| [KOSONG] | [KOSONG] | [KOSONG] |

Contoh: `Gunakan "Aparatur Sipil Negara (ASN)" pada penyebutan pertama | ... | "pegawai negeri"`.

### H.1 Peta kategori WordPress

| jenis_berita | kategori_wordpress | tag_wajib |
|---|---|---|
| kegiatan pimpinan | [KOSONG] | |
| pelayanan publik | [KOSONG] | |
| pengumuman | [KOSONG] | |
| prestasi | [KOSONG] | |
| sosialisasi | [KOSONG] | |

---

## I. Redaksi website

| peran | nama | kanal |
|---|---|---|
| Admin (penerbit) | [KOSONG] | Telegram user_id: [KOSONG] |
| Admin cadangan | [KOSONG] | Telegram user_id: [KOSONG] |

---

## Log perubahan

| tanggal | bagian | perubahan | oleh |
|---|---|---|---|
