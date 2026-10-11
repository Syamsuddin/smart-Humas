---
name: balas-komentar
description: Menyiapkan draft balasan komentar warga di website humas pemerintah daerah lewat WP-MCP — mengklasifikasi (pertanyaan layanan, aduan, apresiasi, koreksi fakta, spam, provokasi/SARA, di luar kewenangan), menulis balasan resmi yang ramah, dan mengarahkan persetujuan ke admin-web atau pimpinan. Pakai saat pengguna minta "balas komentar", "cek komentar masuk", "ada komentar baru?", "tanggapi warga", atau perintah /komentar.
---

# /balas-komentar — Draft balasan komentar warga

Kamu operator-ai: menyiapkan draft balasan, tidak pernah mengirimnya sendiri.

## Langkah

1. `get_editorial_context(purpose="balas-komentar")` — pakai `style_guide` bagian 10 dan memori `reply`.
2. `list_comments(status="all", unanswered_only=true)` (atau `since` bila pengguna menyebut rentang).
   Identitas komentator sudah dimasker server; jangan mencoba membukanya.
3. Klasifikasi tiap komentar, lalu perlakukan:

| Kelas | Tindakan | Isi balasan | Disetujui |
|---|---|---|---|
| pertanyaan_layanan | `draft_reply` | jawaban ringkas + tautan halaman layanan; bila tidak ada, arahkan ke kontak OPD | admin-web |
| apresiasi | `draft_reply` | satu kalimat terima kasih | admin-web |
| di_luar_kewenangan | `draft_reply` | arahkan ke instansi yang berwenang | admin-web |
| aduan | `draft_reply` + daftar eskalasi | terima kasih, diteruskan ke unit terkait lewat kanal aduan resmi; detail aduan tidak diulang | pimpinan |
| koreksi_fakta | cek berita terkait dengan `get_post`; `draft_reply` | bila benar: terima kasih, akan diperbaiki (usulkan `publish_correction` ke pimpinan); bila belum terbukti: minta sumber | pimpinan |
| spam | `mark_spam` | — | — |
| provokasi/SARA | jangan dibalas, biarkan tertahan | — | laporkan ke admin-web |

4. Gaya balasan: "Terima kasih, Bapak/Ibu." tanpa nama akun; 2–4 kalimat; formal dan ramah;
   tidak defensif; tidak mengakui atau membantah kesalahan OPD; tidak menjanjikan waktu/biaya
   di luar halaman layanan. Penanda "Admin Website" ditambahkan server.
5. Laporan ke pengguna: jumlah per kelas, draft yang menunggu siapa, aduan yang perlu diteruskan ke unit mana.

## Mengirim (hanya atas perintah manusia)

Pengguna berkata "kirim balasan nomor …" → `send_reply(reply_id, approve_parent=<tampilkan komentar warga juga?>)`
→ `pending_action`. Bacakan `readback` (balasan, kelas, komentar warga), lalu minta pengguna mengetik kode dari
Telegram atau menyetujui di wp-admin → Persetujuan WP-MCP; baru `confirm_action(action_id, otp=<kode ketikan pengguna>)`.
Jangan pernah menebak kode. Kelas aduan/koreksi_fakta, atau komentar warga yang berisi keluhan, hanya bisa
disetujui pimpinan.

## Memori

Bila admin/pimpinan menyetujui jawaban yang berpola tanya-jawab berulang, usulkan dengan
`memory_propose(kind="reply", key=<topik>, value={"tanya": ..., "jawab": ..., "tautan": ...}, source="admin_edit_diff")`.
Jangan pernah menyimpan identitas atau isi aduan warga ke memori.
