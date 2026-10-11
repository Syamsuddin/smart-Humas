# Plugin Claude Code: wp-mcp-opd

Empat skill redaksi humas di atas server WP-MCP:

| Skill | Untuk |
|---|---|
| `/berita` | draft berita dari foto, caption, nota dinas → perbaikan → ajukan → suntingan & persetujuan pimpinan |
| `/balas-komentar` | klasifikasi komentar warga dan draft balasan, persetujuan admin-web atau pimpinan |
| `/halaman` | halaman layanan, profil OPD, program, PPID dari dokumen sumber + pemeriksa independen |
| `/siapkan-direktori` | wawancara singkat untuk melengkapi Direktori Redaksi (nama pejabat, OPD, singkatan) |

## Pasang di laptop

1. Minta admin server menambahkan kunci SSH Anda (lihat `deploy/authorized_keys.example`).
   Aktor Anda (admin-web atau pimpinan) ditentukan oleh kunci itu.
2. Uji: `ssh -T wpmcp@humas.contoh.go.id < /dev/null` → harus diam menunggu (server MCP berjalan). Tekan Ctrl+C.
3. Set variabel lingkungan (mis. di `~/.bashrc` atau `~/.zshrc`):
   ```bash
   export WPMCP_SSH_TARGET=wpmcp@humas.contoh.go.id
   ```
4. Pasang plugin dari marketplace repo ini (butuh akses baca ke repo):
   ```bash
   claude plugin marketplace add Syamsuddin/smart-Humas
   claude plugin install wp-mcp-opd@smart-humas
   ```
   atau, untuk uji dari salinan lokal: `claude --plugin-dir ./wp-mcp-opd`.
5. **Wajib**: salin aturan izin ke proyek kerja Anda agar Claude Code selalu bertanya sebelum
   mengajukan, menerbitkan, mengirim balasan, atau mengubah Direktori:
   ```bash
   mkdir -p .claude && cp <path-ke>/wp-mcp-opd/templates/claude-settings.json .claude/settings.json
   ```
   Plugin tidak bisa membawa aturan izin sendiri; aturan ini lapis pertama, aksi tertunda di server lapis kedua.
6. Di Claude Code: `/mcp` → pastikan `wp-mcp` tersambung, lalu jalankan `/siapkan-direktori`.

## Validasi

```bash
claude plugin validate ./wp-mcp-opd
```
