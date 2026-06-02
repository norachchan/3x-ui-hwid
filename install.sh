#!/bin/bash

GREEN='\033[032m'
CYAN='\033[036m'
YELLOW='\033[033m'
RED='\033[031m'
NC='\033[0m'

echo -e "${CYAN}===============================================${NC}"
echo -e "${GREEN}           3x-UI HWID Installation            ${NC}"
echo -e "${CYAN}===============================================${NC}"

if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Error: Please run this script as root (sudo)${NC}"
  exit 1
fi

echo -e "\n${YELLOW}[1/5] Installing system dependencies...${NC}"
apt-get update -y
apt-get install -y git python3 python3-pip python3-venv curl

INSTALL_DIR="/root/3x-ui-hwid"
if [ -d "$INSTALL_DIR" ]; then
    echo -e "${YELLOW}Directory $INSTALL_DIR already exists. Updating files...${NC}"
    cd $INSTALL_DIR && git pull
else
    echo -e "${YELLOW}Cloning repository...${NC}"
    git clone https://github.com/Tsimbalist/3x-ui-hwid.git $INSTALL_DIR
    cd $INSTALL_DIR
fi

echo -e "\n${YELLOW}[2/5] Configuring module settings${NC}"

read -p "Enter public port for clients [Default: 2096]: " PORT
PORT=${PORT:-2096}

read -p "Enter 3x-UI subscription URL [Default: http://127.0.0.1:2097]: " THREE_XUI_SUB_URL
THREE_XUI_SUB_URL=${THREE_XUI_SUB_URL:-"http://127.0.0.1:2097"}

read -p "Enable HTTPS? (y/n) [Default: n]: " SSL_ENABLE
SSL_ENABLE=${SSL_ENABLE:-n}
if [[ "$SSL_ENABLE" =~ ^[Yy]$ ]]; then
    read -p "Path to SSL certificate file (fullchain.pem) [Default: /root/cert/ip/fullchain.pem]: " SSL_CERTFILE
    SSL_CERTFILE=${SSL_CERTFILE:-"/root/cert/ip/fullchain.pem"}
    read -p "Path to SSL private key file (privkey.pem) [Default: /root/cert/ip/privkey.pem]: " SSL_KEYFILE
    SSL_KEYFILE=${SSL_KEYFILE:-"/root/cert/ip/privkey.pem"}
else
    SSL_CERTFILE=""
    SSL_KEYFILE=""
fi

read -p "Enter default device limit per key [Default: 3]: " DEFAULT_DEVICE_LIMIT
DEFAULT_DEVICE_LIMIT=${DEFAULT_DEVICE_LIMIT:-3}

read -p "After how many days of inactivity should old devices be unlinked? [Default: 30]: " DEVICE_TTL_DAYS
DEVICE_TTL_DAYS=${DEVICE_TTL_DAYS:-30}

read -p "Error text when limit is exceeded (use underscores instead of spaces) [Default: ⚠️ DEVICE LIMIT REACHED]: " ERROR_PROXY_TEXT
ERROR_PROXY_TEXT=${ERROR_PROXY_TEXT:-"⚠️ DEVICE LIMIT REACHED"}

DEFAULT_TOKEN=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1)
read -p "Enter Secret Master API Token [Press Enter for auto-generation]: " API_BEARER_TOKEN
API_BEARER_TOKEN=${API_BEARER_TOKEN:-$DEFAULT_TOKEN}

cat <<EOF > .env
THREE_XUI_SUB_URL=$THREE_XUI_SUB_URL
PORT=$PORT
HOST=0.0.0.0
DEFAULT_DEVICE_LIMIT=$DEFAULT_DEVICE_LIMIT
DEVICE_TTL_DAYS=$DEVICE_TTL_DAYS
ERROR_PROXY_TEXT=$ERROR_PROXY_TEXT
API_BEARER_TOKEN=$API_BEARER_TOKEN
EOF

echo -e "${GREEN}Configuration successfully saved to .env!${NC}"

echo -e "\n${YELLOW}[3/5] Setting up Python environment...${NC}"
python3 -m venv venv
source venv/bin/activate
pip3 install --upgrade pip
pip3 install -r requirements.txt
deactivate

echo -e "\n${YELLOW}[4/5] Registering module as a Linux system service...${NC}"
cat <<EOF > /etc/systemd/system/3xui-hwid.service
[Unit]
Description=3x-UI HWID
After=network.target

[Service]
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/uvicorn main:app --host 0.0.0.0 --port $PORT $([ -n "$SSL_CERTFILE" ] && echo "--ssl-certfile $SSL_CERTFILE --ssl-keyfile $SSL_KEYFILE")
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable 3xui-hwid
systemctl restart 3xui-hwid

echo -e "\n${GREEN}[5/5] Installation completed successfully!${NC}"
echo -e "${CYAN}====================================================${NC}"
echo -e "Service status: $(systemctl is-active 3xui-hwid)"
echo -e "Module is running on port: ${GREEN}$PORT${NC}"
echo -e "Secret API Token (Bearer): ${YELLOW}$API_BEARER_TOKEN${NC}"
echo -e "${CYAN}====================================================${NC}"
echo -e "Two steps left to complete the setup:"
echo -e "1. In the 3x-UI panel (Panel Settings -> Subscription Settings),"
echo -e "   change the subscription port to match: ${YELLOW}$THREE_XUI_SUB_URL${NC}"
echo -e "2. Use the provided API Token to integrate with your scripts, bots, or web apps."