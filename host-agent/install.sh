#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_PATH=/etc/vortex-netctl/config.json
TEMPLATE_PATH=/etc/vortex-netctl/client-template.json
CONFIG_SOURCE=${VORTEX_NETCTL_CONFIG_SOURCE:-}

validate_config() {
  PYTHONPATH="$SCRIPT_DIR" python3 - "$1" <<'PY'
import json
import sys
from pathlib import Path
from vortex_netctl.config import validate_production_config

path = Path(sys.argv[1])
try:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("config must be a JSON object")
    validate_production_config(raw)
except Exception as exc:
    print(f"Invalid production config {path}: {exc}", file=sys.stderr)
    raise SystemExit(1)
PY
}

install_config() {
  if [[ -e "$CONFIG_PATH" ]] && validate_config "$CONFIG_PATH"; then
    echo "Preserving existing validated production config: $CONFIG_PATH"
    return
  fi

  if [[ -e "$CONFIG_PATH" ]]; then
    echo "Existing config is missing required values or contains example placeholders: $CONFIG_PATH" >&2
  else
    echo "Production config does not exist: $CONFIG_PATH" >&2
  fi
  [[ -n "$CONFIG_SOURCE" ]] || {
    echo "Refusing to install config.example.json. Create a local production JSON config and rerun with VORTEX_NETCTL_CONFIG_SOURCE=/path/to/config.json." >&2
    exit 1
  }
  [[ -f "$CONFIG_SOURCE" ]] || { echo "Config source does not exist: $CONFIG_SOURCE" >&2; exit 1; }
  validate_config "$CONFIG_SOURCE"
  install -o root -g vortex-netctl -m 0640 "$CONFIG_SOURCE" "$CONFIG_PATH"
  echo "Installed validated production config from explicit source."
}

install_template() {
  if [[ -e "$TEMPLATE_PATH" ]]; then
    echo "Preserving existing client template: $TEMPLATE_PATH"
    return
  fi
  install -o root -g root -m 0640 "$SCRIPT_DIR/client-template.json" "$TEMPLATE_PATH"
  echo "Installed default client template: $TEMPLATE_PATH"
}
[[ ${EUID} -eq 0 ]] || { echo "Run explicitly with: sudo ./host-agent/install.sh"; exit 1; }
echo "VORTEX host-agent installation summary"
echo "- installs Python agent under /opt/vortex-netctl"
echo "- requires an explicit validated production config; never installs config.example.json"
echo "- preserves an existing validated /etc/vortex-netctl/config.json"
echo "- installs /etc/vortex-netctl/client-template.json only if absent"
echo "- creates /var/lib/vortex-netctl/backups and client-template-versions (root-only)"
echo "- installs root systemd service vortex-netctl.service"
echo "- creates administrative and restricted subscription sockets as root:vortex-netctl mode 0660"
echo "- agent has only hard-coded JSON/RPC operations; no shell or arbitrary file API"
read -r -p "Proceed? [y/N] " answer
[[ "$answer" =~ ^[Yy]$ ]] || exit 0
command -v systemctl >/dev/null || { echo "systemd is required"; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required"; exit 1; }
command -v /usr/bin/sing-box >/dev/null || { echo "/usr/bin/sing-box is required"; exit 1; }
command -v /usr/bin/docker >/dev/null || { echo "/usr/bin/docker is required"; exit 1; }
getent group vortex-netctl >/dev/null || groupadd --system vortex-netctl
install -d -o root -g vortex-netctl -m 0750 /etc/vortex-netctl /var/lib/vortex-netctl /var/lib/vortex-netctl/backups /var/lib/vortex-netctl/client-template-versions /var/lib/hyvpn-vortex /run/vortex-netctl /run/vortex-subscription
install_config
install_template
install -d -o root -g root -m 0755 /opt/vortex-netctl
cp -a "$SCRIPT_DIR/vortex_netctl" /opt/vortex-netctl/
python3 -m venv /opt/vortex-netctl/venv
/opt/vortex-netctl/venv/bin/pip install --no-cache-dir -r "$SCRIPT_DIR/requirements.txt"
install -m 0644 "$SCRIPT_DIR/vortex-netctl.service" /etc/systemd/system/vortex-netctl.service
install -m 0644 "$SCRIPT_DIR/tmpfiles.conf" /etc/tmpfiles.d/vortex-netctl.conf
systemctl daemon-reload
systemd-tmpfiles --create /etc/tmpfiles.d/vortex-netctl.conf
systemctl enable vortex-netctl.service
systemctl restart vortex-netctl.service
if ! systemctl is-active --quiet vortex-netctl.service; then
  echo "vortex-netctl.service failed to become active after installation" >&2
  systemctl --no-pager --full status vortex-netctl.service >&2 || true
  exit 1
fi
echo "vortex-netctl GID: $(getent group vortex-netctl | cut -d: -f3)"
echo "Set VORTEX_NETCTL_GID to this value in the panel .env before starting Docker."
systemctl --no-pager --full status vortex-netctl.service