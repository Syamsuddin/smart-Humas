=== WP-MCP Bridge ===
Contributors: syamsuddinideris
Tags: mcp, ai, humas, government, workflow
Requires at least: 6.4
Tested up to: 6.8
Requires PHP: 8.0
Stable tag: 1.2.0
License: GPLv2 or later
License URI: https://www.gnu.org/licenses/gpl-2.0.html

Jembatan tipis antara WordPress dan server WP-MCP untuk website humas pemerintah daerah.

== Description ==

* Peran "Editor AI" (editor_ai) untuk akun yang dipakai WP-MCP. Bukan Administrator.
* Meta alur kerja _wpmcp_* (draft → revisi → siap_tayang → tayang) terbaca lewat REST.
* Akun Editor AI hanya diterima dari server sendiri (127.0.0.1/::1) dan tidak bisa login wp-admin.
  Tambahkan IP lain di wp-config.php bila perlu: define( 'WPMCP_ALLOWED_IPS', array( '10.0.0.5' ) );
* Endpoint /wp-json/wpmcp/v1/ping dan /wp-json/wpmcp/v1/search-stats.
* Kotak "Status WP-MCP" di editor dan gaya kotak ralat/pencabutan.

Seluruh kebijakan peran, persetujuan, pemeriksa nama, dan pemasker data pribadi berada di server WP-MCP.

== Installation ==

1. Unggah folder wp-mcp-bridge ke wp-content/plugins/ lalu aktifkan.
2. Buat pengguna baru (mis. editor-ai) dengan peran "Editor AI".
3. Profil pengguna itu → Application Passwords → buat satu, salin ke /etc/wp-mcp/secrets.env.
