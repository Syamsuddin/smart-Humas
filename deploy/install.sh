#!/usr/bin/env bash
# Pemasang WP-MCP di VPS Ubuntu 22.04/24.04 tempat WordPress humas berjalan.
#
#   sudo ./deploy/install.sh --wp-path /var/www/html --site-url https://humas.contoh.go.id
#
# Yang dilakukan (idempoten, aman diulang):
#   1. paket sistem: python3-venv, tesseract (ind), WP-CLI bila belum ada
#   2. user sistem 'wpmcp', folder /opt/wp-mcp, /etc/wp-mcp, /var/lib/wp-mcp, /var/log/wp-mcp
#   3. virtualenv + paket wp-mcp
#   4. plugin wp-mcp-bridge diaktifkan, akun 'editor-ai' (peran Editor AI) + application password
#   5. secrets.env, config.yaml, actors.yaml (dari contoh, tidak menimpa yang sudah ada)
#   6. sudoers: wpmcp hanya boleh menjalankan /opt/wp-mcp/bin/wp-safe (whitelist ditegakkan di balik sudo)
#   7. /etc/hosts: domain situs → 127.0.0.1 agar REST akun AI datang dari loopback
#   8. logrotate untuk audit.jsonl
set -euo pipefail

WP_PATH=""
SITE_URL=""
WP_OWNER="www-data"
WITH_FACES=0
SKIP_HOSTS=0
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() { sed -n '2,16p' "$0"; exit 1; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --wp-path) WP_PATH="$2"; shift 2 ;;
    --site-url) SITE_URL="$2"; shift 2 ;;
    --wp-owner) WP_OWNER="$2"; shift 2 ;;
    --with-faces) WITH_FACES=1; shift ;;      # opencv untuk crop wajah (±60 MB)
    --skip-hosts) SKIP_HOSTS=1; shift ;;
    -h|--help) usage ;;
    *) echo "Argumen tidak dikenal: $1"; usage ;;
  esac
done
[[ $EUID -eq 0 ]] || { echo "Jalankan dengan sudo."; exit 1; }
[[ -n "$WP_PATH" && -f "$WP_PATH/wp-config.php" ]] || { echo "--wp-path harus folder WordPress (berisi wp-config.php)."; exit 1; }
[[ -n "$SITE_URL" ]] || { echo "--site-url wajib, mis. https://humas.contoh.go.id"; exit 1; }
DOMAIN="$(echo "$SITE_URL" | sed -E 's#^https?://##; s#/.*$##')"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

say "1. Paket sistem"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip tesseract-ocr tesseract-ocr-ind sudo curl >/dev/null
if ! command -v wp >/dev/null 2>&1; then
  curl -fsSL -o /usr/local/bin/wp https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar
  chmod +x /usr/local/bin/wp
fi
WP_BIN="$(command -v wp)"
wpcli() { sudo -u "$WP_OWNER" "$WP_BIN" --path="$WP_PATH" "$@"; }

say "2. User dan folder"
id wpmcp >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/wp-mcp --shell /bin/bash wpmcp
install -d -o wpmcp -g wpmcp -m 750 /var/lib/wp-mcp /var/lib/wp-mcp/inbox /var/log/wp-mcp
install -d -o root -g wpmcp -m 750 /etc/wp-mcp
install -d -o root -g root -m 755 /opt/wp-mcp /opt/wp-mcp/bin
# authorized_keys milik root: proses wpmcp yang disusupi tidak bisa menambah kunci/aktor baru
install -d -o root -g root -m 755 /var/lib/wp-mcp/.ssh
[[ -f /var/lib/wp-mcp/.ssh/authorized_keys ]] || install -o root -g root -m 644 /dev/null /var/lib/wp-mcp/.ssh/authorized_keys

say "3. Virtualenv dan paket wp-mcp"
rm -rf /opt/wp-mcp/src && cp -r "$SRC_DIR/wp-mcp" /opt/wp-mcp/src
python3 -m venv /opt/wp-mcp/venv
EXTRAS="db"; [[ $WITH_FACES -eq 1 ]] && EXTRAS="db,faces"
/opt/wp-mcp/venv/bin/pip install -q --upgrade pip
/opt/wp-mcp/venv/bin/pip install -q "/opt/wp-mcp/src[$EXTRAS]"
install -o root -g root -m 755 "$SRC_DIR/deploy/wp-mcp-launch" /opt/wp-mcp/bin/wp-mcp-launch
install -o root -g root -m 755 "$SRC_DIR/deploy/wp-safe" /opt/wp-mcp/bin/wp-safe
install -o root -g root -m 644 "$SRC_DIR/wp-mcp/wp_mcp/data/cli_whitelist.yaml" /opt/wp-mcp/cli_whitelist.yaml
printf '{"wp_bin": "%s", "wp_path": "%s", "whitelist": "/opt/wp-mcp/cli_whitelist.yaml"}\n' "$WP_BIN" "$WP_PATH" > /opt/wp-mcp/wp-safe.json
chown root:root /opt/wp-mcp/wp-safe.json && chmod 644 /opt/wp-mcp/wp-safe.json

say "4. Plugin wp-mcp-bridge dan akun editor-ai"
rm -rf "$WP_PATH/wp-content/plugins/wp-mcp-bridge"
cp -r "$SRC_DIR/wp-mcp-bridge" "$WP_PATH/wp-content/plugins/wp-mcp-bridge"
chown -R "$WP_OWNER":"$WP_OWNER" "$WP_PATH/wp-content/plugins/wp-mcp-bridge"
wpcli plugin activate wp-mcp-bridge >/dev/null
if ! wpcli user get editor-ai --field=ID >/dev/null 2>&1; then
  wpcli user create editor-ai "editor-ai@$DOMAIN" --role=editor_ai --display_name="Editor AI" \
    --user_pass="$(head -c 32 /dev/urandom | base64)" >/dev/null
fi
wpcli user set-role editor-ai editor_ai >/dev/null

say "5. Konfigurasi dan kunci bridge"
EX=/opt/wp-mcp/src/wp_mcp/data
if [[ ! -f /etc/wp-mcp/secrets.env ]]; then
  APP_PW="$(wpcli user application-password create editor-ai wp-mcp --porcelain)"
  {
    echo "WPMCP_WP_USER=editor-ai"
    echo "WPMCP_WP_APP_PASSWORD=\"$APP_PW\""
    echo "WPMCP_TELEGRAM_TOKEN="
  } > /etc/wp-mcp/secrets.env
fi
if ! grep -q '^WPMCP_BRIDGE_KEY=' /etc/wp-mcp/secrets.env; then
  BRIDGE_KEY="$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 40)"
  echo "WPMCP_BRIDGE_KEY=$BRIDGE_KEY" >> /etc/wp-mcp/secrets.env
  "$WP_BIN" --allow-root --path="$WP_PATH" config set WPMCP_BRIDGE_KEY "$BRIDGE_KEY" --type=constant --quiet
fi
chown root:wpmcp /etc/wp-mcp/secrets.env && chmod 640 /etc/wp-mcp/secrets.env
if [[ ! -f /etc/wp-mcp/config.yaml ]]; then
  sed -e "s#https://humas.contoh.go.id#$SITE_URL#" -e "s#/var/www/html#$WP_PATH#" \
      -e "s#/usr/local/bin/wp\"#/opt/wp-mcp/bin/wp-safe\"#" -e "s#wp_cli_sudo_user: \"www-data\"#wp_cli_sudo_user: \"$WP_OWNER\"#" \
      "$EX/config.example.yaml" > /etc/wp-mcp/config.yaml
fi
[[ -f /etc/wp-mcp/actors.yaml ]] || cp "$EX/actors.example.yaml" /etc/wp-mcp/actors.yaml
[[ -f /etc/wp-mcp/direktori-redaksi.md ]] || cp "$EX/direktori-redaksi.md" /etc/wp-mcp/direktori-redaksi.md
chown root:wpmcp /etc/wp-mcp/*.yaml /etc/wp-mcp/*.md && chmod 640 /etc/wp-mcp/*.yaml /etc/wp-mcp/*.md

say "6. sudoers (wpmcp → wp-safe sebagai $WP_OWNER saja)"
echo "wpmcp ALL=($WP_OWNER) NOPASSWD: /opt/wp-mcp/bin/wp-safe" > /etc/sudoers.d/wp-mcp
chmod 440 /etc/sudoers.d/wp-mcp
visudo -cf /etc/sudoers.d/wp-mcp >/dev/null

if [[ $SKIP_HOSTS -eq 0 ]] && ! grep -qE "^127\.0\.0\.1\s+.*\b$DOMAIN\b" /etc/hosts; then
  say "7. /etc/hosts: $DOMAIN → 127.0.0.1"
  echo "127.0.0.1 $DOMAIN # wp-mcp: REST akun AI lewat loopback" >> /etc/hosts
fi

say "8. logrotate"
cat > /etc/logrotate.d/wp-mcp <<'EOF'
/var/log/wp-mcp/audit.jsonl {
    monthly
    rotate 24
    compress
    delaycompress
    missingok
    notifempty
    create 0640 wpmcp wpmcp
}
EOF

say "Pemeriksaan"
sudo -u wpmcp WPMCP_CONFIG_DIR=/etc/wp-mcp /opt/wp-mcp/venv/bin/wp-mcp check | head -60 || true

cat <<EOF

Selesai. Langkah berikutnya:
  1. Isi /etc/wp-mcp/actors.yaml (admin-web dan pimpinan), termasuk wp_user (login WordPress
     masing-masing) untuk halaman wp-admin → Persetujuan WP-MCP.
  2. Tambahkan kunci SSH tiap orang ke /var/lib/wp-mcp/.ssh/authorized_keys, contoh:
       command="/opt/wp-mcp/bin/wp-mcp-launch --actor admin1",restrict ssh-ed25519 AAAA... admin1@laptop
  3. Telegram (opsional, wajib untuk OTP level 3): isi WPMCP_TELEGRAM_TOKEN di secrets.env,
     notify.telegram.enabled: true di config.yaml, dan telegram_user_id di actors.yaml.
  4. Di laptop: pasang plugin Claude Code wp-mcp-opd, lalu jalankan /siapkan-direktori.
EOF
