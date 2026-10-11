# wp-mcp

Server MCP (Python ≥3.11, SDK `mcp` 2.x) untuk website humas pemerintah daerah. Lihat README di akar repo
untuk gambaran, `docs/KEAMANAN.md` untuk model keamanan, dan `deploy/install.sh` untuk pemasangan.

```bash
pip install -e '.[dev]'
python -m pytest -q
wp-mcp tools                                   # daftar tool, level, peran
WPMCP_CONFIG_DIR=/etc/wp-mcp wp-mcp check      # pemeriksaan situs
wp-mcp serve --actor admin1                    # server MCP stdio (dipanggil launcher SSH)
```

Struktur: `policy.py` (registri + Dispatcher: peran, level, persetujuan, audit) · `tools/` (48 tool) ·
`doors/` (REST, WP-CLI, DB baca-saja, OS) · `adapters/` (cache, keamanan) · `names.py` (pemeriksa nama) ·
`markdown_blocks.py` (Markdown → Gutenberg) · `images.py` (foto) · `pii.py` · `directory_md.py` · `wp_safe.py`.

Lisensi komersial, Syamsuddin Ideris (syamsuddin.ideris@gmail.com).
