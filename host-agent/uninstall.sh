#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
[[ ${EUID} -eq 0 ]] || { echo "Run explicitly with: sudo ./host-agent/uninstall.sh"; exit 1; }
echo "Removes only the vortex-netctl program and systemd unit."
echo "Preserves /etc/vortex-netctl and /var/lib/vortex-netctl backups/configuration."
read -r -p "Proceed? [y/N] " answer
[[ "$answer" =~ ^[Yy]$ ]] || exit 0
systemctl disable --now vortex-netctl.service 2>/dev/null || true
rm -f /etc/systemd/system/vortex-netctl.service /etc/tmpfiles.d/vortex-netctl.conf
rm -rf /opt/vortex-netctl
systemctl daemon-reload