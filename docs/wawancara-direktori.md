---
name: wawancara-direktori
bagian_dari: skill /siapkan-direktori (plugin wp-mcp-opd)
versi: 1.0
penulis: syamsuddin.ideris@gmail.com
---

# Protokol Wawancara Singkat — Melengkapi Direktori Redaksi

Dipakai saat `direktori-redaksi.md` belum `lengkap-wajib`, saat `verify_names` menemukan
nama yang tidak dikenal, atau saat Admin mengetik `/siapkan-direktori`.
Tujuannya: melengkapi data dengan pertanyaan sesedikit mungkin, tanpa pernah mengarang isi.

## Prinsip

1. **Periksa dulu, tanya kemudian.** Hitung bidang `[KOSONG]` dan `verif: tidak`. Jangan
   menanyakan sesuatu yang sudah terisi.
2. **Wajib dulu.** Urutan: B (OPD pemilik) → D (pejabat) → C (unit) → A (pemda) → I → H.1 → sisanya.
3. **Satu putaran maksimal 5 pertanyaan**, dikelompokkan per bagian. Admin sibuk; wawancara
   yang terasa seperti formulir 40 baris akan ditinggalkan.
4. **Tawarkan jalan pintas di putaran pertama**: tempel tabel dari Excel/SIMPEG, foto SK atau
   papan struktur, atau PDF Perbup SOTK. Satu tempelan bisa menggantikan 20 pertanyaan.
5. **Tidak pernah menebak.** Gelar, ejaan nama, dan tanggal hanya dari Admin atau dokumen.
   Isian dari pengetahuan umum Claude tidak boleh ditulis, termasuk nama pejabat yang
   "kelihatannya" benar.
6. **Ulang balik untuk dicek.** Setiap jawaban dikembalikan dalam bentuk tabel yang akan
   disimpan, dan Admin menjawab "sah" atau mengoreksi. Baru setelah "sah" kolom `verif`
   menjadi `ya`.
7. **Catat sumber.** Jawaban ketik Admin → `sumber: admin`; dari dokumen → nama dokumennya.

## Alur

```
1. directory_status (bidang kosong, urut prioritas) dan directory_lookup
2. hitung kekosongan per bagian → tentukan putaran berikutnya
3. putaran pertama: tawarkan jalan pintas (tempel tabel / unggah dokumen)
4. bila ada dokumen: ekstrak → tampilkan tabel hasil ekstraksi → minta "sah" / koreksi
5. bila tidak: ajukan ≤5 pertanyaan bagian prioritas
6. tampilkan tabel hasil → "sah" / koreksi
7. tulis ke direktori: directory_set per rekaman, atau directory_import untuk tabel besar (log otomatis)
8. ulangi sampai status lengkap-wajib; tawarkan bagian opsional sekali, jangan memaksa
```

## Contoh pesan putaran pertama

> Pak/Bu, Direktori Redaksi website [situs] baru terisi [n] dari [m] bidang wajib.
> Cara tercepat: tempelkan daftar pejabat struktural (Excel/ekspor SIMPEG) atau unggah
> foto bagan struktur. Kalau belum ada, saya tanya lima hal dulu:
>
> 1. Nama resmi OPD dan singkatan resminya?
> 2. Singkatan apa yang sering salah dipakai orang dan harus dihindari?
> 3. Nama lengkap bergelar Kepala OPD dan sejak kapan menjabat?
> 4. Bagaimana kredit foto yang biasa dipakai? (contoh: `(Foto: Humas Setda Contoh)`)
> 5. Alamat kantor yang dicantumkan di website?

## Contoh pesan konfirmasi

> Ini yang akan saya simpan di Direktori, mohon dicek:
>
> | jabatan_resmi | nama_lengkap_bergelar | sebutan_berikutnya | sejak |
> |---|---|---|---|
> | Kepala [OPD] | [jawaban Admin] | [jawaban Admin] | [jawaban Admin] |
>
> Balas **sah**, atau tulis koreksinya.

## Pemicu wawancara mini (di tengah kerja)

Saat `/berita` menemukan nama yang tidak ada di Direktori, skill tidak berhenti total:

1. Draft tetap dibuat dengan tanda `[NAMA BELUM TERVERIFIKASI: ...]`.
2. Di akhir, ajukan satu pertanyaan saja:
   > Di bahan ada "[nama] — [jabatan]". Belum ada di Direktori. Apakah ejaan dan jabatannya
   > sudah benar? (balas **benar**, atau tulis yang benar)
3. Jawaban "benar" → simpan dengan `sumber: admin`, `verif: ya`, dan hapus tanda di draft.

## Kriteria selesai

- [ ] Semua bidang `[WAJIB]` di bagian A, B, C, D, I terisi dan `verif: ya`
- [ ] `status` di frontmatter = `lengkap-wajib`
- [ ] `directory_import` berhasil tanpa galat
- [ ] Uji cepat: `verify_names` atas 3 berita lama tidak memunculkan nama pejabat OPD sebagai "tidak dikenal"

## Yang tidak dilakukan

- Tidak menanyakan NIP, nomor HP pribadi, atau alamat rumah pejabat.
- Tidak mengisi nama dari pencarian web atau ingatan model.
- Tidak menanyakan ulang bidang yang sudah `verif: ya`, kecuali `memory_stale_report` menandainya basi.
