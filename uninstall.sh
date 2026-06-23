#!/bin/bash
set -euo pipefail

INSTALL_DIR="${HWID_INSTALL_DIR:-/root/3x-ui-hwid}"

if [[ "$EUID" -ne 0 ]]; then
  echo "Run as root"
  exit 1
fi

systemctl stop 3xui-hwid 2>/dev/null || true
systemctl disable 3xui-hwid 2>/dev/null || true
rm -f /etc/systemd/system/3xui-hwid.service
systemctl daemon-reload

echo "HWID service removed."
echo "Files kept in: $INSTALL_DIR"
echo "To restore 3x-ui subscription on port 2096 manually, edit $INSTALL_DIR/../ or /etc/x-ui/x-ui.db"
