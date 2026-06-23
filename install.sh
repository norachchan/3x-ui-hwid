#!/bin/bash
set -euo pipefail

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

REPO_URL="${HWID_REPO_URL:-https://github.com/norachchan/3x-ui-hwid.git}"
INSTALL_DIR="${HWID_INSTALL_DIR:-/root/3x-ui-hwid}"
XUI_DB="${XUI_DB_PATH:-/etc/x-ui/x-ui.db}"
PUBLIC_PORT="${HWID_PUBLIC_PORT:-2096}"
INTERNAL_PORT="${HWID_INTERNAL_PORT:-2097}"
AUTO_YES=false

for arg in "$@"; do
  case "$arg" in
    -y|--yes) AUTO_YES=true ;;
  esac
done

log()  { echo -e "${GREEN}[+]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[x]${NC} $*" >&2; }

prompt() {
  local var_name="$1" prompt_text="$2" default_value="$3"
  if $AUTO_YES; then
    printf -v "$var_name" '%s' "$default_value"
    return
  fi
  read -r -p "$prompt_text [$default_value]: " input
  printf -v "$var_name" '%s' "${input:-$default_value}"
}

detect_public_ip() {
  curl -4 -fsS --max-time 5 ifconfig.me 2>/dev/null \
    || curl -4 -fsS --max-time 5 api.ipify.org 2>/dev/null \
    || hostname -I 2>/dev/null | awk '{print $1}' \
    || echo "127.0.0.1"
}

read_xui_setting() {
  local key="$1" default="$2"
  if [[ ! -f "$XUI_DB" ]]; then
    echo "$default"
    return
  fi
  python3 - "$XUI_DB" "$key" "$default" <<'PY'
import sqlite3, sys
db, key, default = sys.argv[1:4]
try:
    c = sqlite3.connect(db)
    row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    print(row[0] if row and row[0] is not None else default)
except Exception:
    print(default)
PY
}

configure_xui_subscription() {
  local public_ip="$1" sub_path="$2"
  sub_path="${sub_path#/}"
  sub_path="${sub_path%/}"
  local sub_uri="http://${public_ip}:${PUBLIC_PORT}/${sub_path}/"

  if [[ ! -f "$XUI_DB" ]]; then
    warn "База 3x-ui не найдена ($XUI_DB). Настройте подписку вручную:"
    warn "  subPort=$INTERNAL_PORT, subListen=127.0.0.1, subURI=$sub_uri"
    return 1
  fi

  python3 - "$XUI_DB" "$INTERNAL_PORT" "$sub_uri" <<'PY'
import sqlite3, sys
db, internal_port, sub_uri = sys.argv[1:4]
c = sqlite3.connect(db)
updates = {
    "subPort": internal_port,
    "subListen": "127.0.0.1",
    "subURI": sub_uri,
}
for k, v in updates.items():
    if c.execute("SELECT 1 FROM settings WHERE key=?", (k,)).fetchone():
        c.execute("UPDATE settings SET value=? WHERE key=?", (v, k))
    else:
        c.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (k, v))
c.commit()
print(sub_uri)
PY
}

echo -e "${CYAN}===============================================${NC}"
echo -e "${GREEN}       3x-UI HWID — установка одной командой     ${NC}"
echo -e "${CYAN}===============================================${NC}"

if [[ "$EUID" -ne 0 ]]; then
  err "Запустите от root: sudo bash install.sh"
  exit 1
fi

if ! command -v x-ui >/dev/null 2>&1 && [[ ! -f /usr/local/x-ui/x-ui ]]; then
  err "3x-ui не найден. Сначала установите панель:"
  err "  bash <(curl -Ls https://raw.githubusercontent.com/mhsanaei/3x-ui/master/install.sh)"
  exit 1
fi

log "[1/7] Установка зависимостей..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y >/dev/null
apt-get install -y git python3 python3-venv python3-pip curl sqlite3 >/dev/null

log "[2/7] Загрузка исходников..."
if [[ -d "$INSTALL_DIR/.git" ]]; then
  git -C "$INSTALL_DIR" pull --ff-only || warn "git pull не удался, используем локальную копию"
else
  rm -rf "$INSTALL_DIR"
  git clone "$REPO_URL" "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"

# curl | bash запускает закэшированную копию; после git pull — актуальный install.sh с диска
LOCAL_SCRIPT="$INSTALL_DIR/install.sh"
RUNNING_SCRIPT="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null || realpath "${BASH_SOURCE[0]}" 2>/dev/null || echo "${BASH_SOURCE[0]}")"
RESOLVED_LOCAL="$(readlink -f "$LOCAL_SCRIPT" 2>/dev/null || realpath "$LOCAL_SCRIPT" 2>/dev/null || echo "$LOCAL_SCRIPT")"
if [[ -f "$LOCAL_SCRIPT" && "$RUNNING_SCRIPT" != "$RESOLVED_LOCAL" ]]; then
  log "Перезапуск актуального install.sh с диска..."
  exec bash "$LOCAL_SCRIPT" "$@"
fi

PUBLIC_IP="$(detect_public_ip)"
SUB_PATH="$(read_xui_setting subPath '/subs/')"
SUB_PATH="${SUB_PATH#/}"
SUB_PATH="${SUB_PATH%/}"

log "[3/7] Настройка 3x-ui (внутренний порт $INTERNAL_PORT, публичный $PUBLIC_PORT)..."
SUB_URI="$(configure_xui_subscription "$PUBLIC_IP" "$SUB_PATH" || true)"
if [[ -n "${SUB_URI:-}" ]]; then
  log "subURI → $SUB_URI"
  if systemctl is-active x-ui >/dev/null 2>&1; then
    systemctl restart x-ui
    sleep 2
  fi
fi

log "[4/7] Конфигурация HWID..."
prompt DEFAULT_DEVICE_LIMIT "Лимит устройств по умолчанию" "3"
prompt DEVICE_TTL_DAYS "Отвязка неактивных устройств (дней)" "30"
prompt ERROR_PROXY_TEXT "Текст при превышении лимита" "⚠️ ЛИМИТ УСТРОЙСТВ ДОСТИГНУТ"
prompt TRUSTED_IPS "Доверенные IP без x-hwid (через запятую, для агрегаторов)" ""

generate_api_token() {
  python3 -c "import secrets; print(secrets.token_urlsafe(24))"
}

if [[ -f .env ]] && grep -q '^API_BEARER_TOKEN=' .env; then
  API_BEARER_TOKEN="$(grep '^API_BEARER_TOKEN=' .env | cut -d= -f2-)"
  log "Сохранён существующий API_BEARER_TOKEN"
else
  API_BEARER_TOKEN="$(generate_api_token)"
fi

if ! $AUTO_YES; then
  read -r -p "API Bearer Token [Enter = оставить/сгенерировать]: " token_input
  [[ -n "$token_input" ]] && API_BEARER_TOKEN="$token_input"
fi

cat > .env <<EOF
THREE_XUI_SUB_URL=http://127.0.0.1:${INTERNAL_PORT}
PORT=${PUBLIC_PORT}
HOST=0.0.0.0
SUB_PATH=${SUB_PATH}
PUBLIC_HOST=${PUBLIC_IP}
DEFAULT_DEVICE_LIMIT=${DEFAULT_DEVICE_LIMIT}
DEVICE_TTL_DAYS=${DEVICE_TTL_DAYS}
ERROR_PROXY_TEXT=${ERROR_PROXY_TEXT}
API_BEARER_TOKEN=${API_BEARER_TOKEN}
TRUSTED_IPS=${TRUSTED_IPS}
EOF
chmod 600 .env

log "[5/7] Python venv..."
python3 -m venv venv
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q -r requirements.txt

log "[6/7] systemd сервис..."
cat > /etc/systemd/system/3xui-hwid.service <<EOF
[Unit]
Description=3x-UI HWID Proxy
After=network.target x-ui.service
Wants=x-ui.service

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${INSTALL_DIR}/.env
ExecStart=${INSTALL_DIR}/venv/bin/uvicorn main:app --host 0.0.0.0 --port ${PUBLIC_PORT}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable 3xui-hwid >/dev/null
systemctl restart 3xui-hwid

if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow "${PUBLIC_PORT}/tcp" >/dev/null 2>&1 || true
  log "UFW: открыт порт ${PUBLIC_PORT}/tcp"
fi

log "[7/7] Проверка..."
sleep 2
HWID_STATUS="$(systemctl is-active 3xui-hwid 2>/dev/null || echo failed)"
XUI_STATUS="$(systemctl is-active x-ui 2>/dev/null || echo unknown)"

echo
echo -e "${CYAN}===============================================${NC}"
echo -e "${GREEN}Установка завершена${NC}"
echo -e "${CYAN}===============================================${NC}"
echo -e "HWID сервис:     ${GREEN}${HWID_STATUS}${NC} (порт ${PUBLIC_PORT})"
echo -e "3x-ui подписка:  ${GREEN}${XUI_STATUS}${NC} (внутренний ${INTERNAL_PORT})"
echo -e "Публичный IP:    ${YELLOW}${PUBLIC_IP}${NC}"
echo -e "URL подписки:    ${YELLOW}http://${PUBLIC_IP}:${PUBLIC_PORT}/${SUB_PATH}/{sub_id}${NC}"
echo -e "API Token:       ${YELLOW}${API_BEARER_TOKEN}${NC}"
echo -e "Конфиг:          ${INSTALL_DIR}/.env"
echo
echo -e "Команды:"
echo -e "  systemctl status 3xui-hwid"
echo -e "  systemctl restart 3xui-hwid"
echo -e "  journalctl -u 3xui-hwid -f"
echo
echo -e "Master API:"
echo -e "  GET  /api/sub/{sub_id}/devices"
echo -e "  POST /api/sub/{sub_id}/limit/{N}"
echo -e "  DELETE /api/sub/{sub_id}/reset"
echo -e "${CYAN}===============================================${NC}"
