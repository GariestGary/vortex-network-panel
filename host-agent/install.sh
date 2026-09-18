#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
[[ ${EUID} -eq 0 ]] || { echo "Run explicitly with: sudo ./host-agent/install.sh"; exit 1; }
echo "VORTEX host-agent installation summary"
echo "- installs Python agent under /opt/vortex-netctl"
echo "- creates/reuses Unix group vortex-netctl"
echo "- creates /etc/vortex-netctl/config.json (root-only) if absent"
echo "- creates /var/lib/vortex-netctl/backups (root-only)"
echo "- installs root systemd service vortex-netctl.service"
echo "- creates socket /run/vortex-netctl/vortex-netctl.sock as root:vortex-netctl mode 0660"
echo "- agent has only hard-coded JSON/RPC operations; no shell or arbitrary file API"
read -r -p "Proceed? [y/N] " answer
[[ "$answer" =~ ^[Yy]$ ]] || exit 0
command -v systemctl >/dev/null || { echo "systemd is required"; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required"; exit 1; }
command -v /usr/bin/sing-box >/dev/null || { echo "/usr/bin/sing-box is required"; exit 1; }
command -v /usr/bin/docker >/dev/null || { echo "/usr/bin/docker is required"; exit 1; }
getent group vortex-netctl >/dev/null || groupadd --system vortex-netctl
install -d -o root -g vortex-netctl -m 0750 /etc/vortex-netctl /var/lib/vortex-netctl /var/lib/vortex-netctl/backups /run/vortex-netctl
install -d -o root -g root -m 0755 /opt/vortex-netctl
cp -a "$SCRIPT_DIR/vortex_netctl" /opt/vortex-netctl/
python3 -m venv /opt/vortex-netctl/venv
/opt/vortex-netctl/venv/bin/pip install --no-cache-dir -r "$SCRIPT_DIR/requirements.txt"
[[ -e /etc/vortex-netctl/config.json ]] || install -o root -g vortex-netctl -m 0640 "$SCRIPT_DIR/config.example.json" /etc/vortex-netctl/config.json
install -m 0644 "$SCRIPT_DIR/vortex-netctl.service" /etc/systemd/system/vortex-netctl.service
install -m 0644 "$SCRIPT_DIR/tmpfiles.conf" /etc/tmpfiles.d/vortex-netctl.conf
systemctl daemon-reload
systemd-tmpfiles --create /etc/tmpfiles.d/vortex-netctl.conf
systemctl enable --now vortex-netctl.service
echo "vortex-netctl GID: $(getent group vortex-netctl | cut -d: -f3)"
echo "Set VORTEX_NETCTL_GID to this value in the panel .env before starting Docker."
systemctl --no-pager --full status vortex-netctl.service