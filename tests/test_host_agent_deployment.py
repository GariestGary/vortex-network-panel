import json
import subprocess
import sys
from pathlib import Path

import pytest


HOST_AGENT = Path("host-agent").resolve()
sys.path.insert(0, str(HOST_AGENT))
from vortex_netctl.config import load_config, validate_production_config


def production_config():
    return {
        "sing_box_config": "/etc/sing-box/config.json",
        "force_vpn": "/etc/sing-box/rules/force-vpn.json",
        "force_direct": "/etc/sing-box/rules/force-direct.json",
        "backups": "/var/lib/vortex-netctl/backups",
        "lock_file": "/run/lock/vortex-netctl.lock",
        "socket_path": "/run/vortex-netctl/vortex-netctl.sock",
        "lan_host": "192.168.10.20",
        "lan_port": 2443,
        "lan_ssid": "ProductionNetwork",
        "remote_domain": "gateway.production.example",
        "remote_port": 443,
        "ip_endpoint": "https://api.ipify.org",
    }


def test_agent_module_imports_from_systemd_working_directory():
    result = subprocess.run(
        [sys.executable, "-c", "import vortex_netctl.agent"],
        cwd=HOST_AGENT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_systemd_unit_sets_agent_working_directory_without_relaxing_sandbox():
    unit = (HOST_AGENT / "vortex-netctl.service").read_text(encoding="utf-8")
    assert "WorkingDirectory=/opt/vortex-netctl" in unit
    assert "ExecStart=/opt/vortex-netctl/venv/bin/python -m vortex_netctl.agent" in unit
    for setting in ("User=root", "Group=vortex-netctl", "NoNewPrivileges=true", "ProtectHome=true", "ProtectSystem=strict"):
        assert setting in unit


def test_placeholder_config_is_rejected(tmp_path):
    placeholder = json.loads((HOST_AGENT / "config.example.json").read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match="placeholder"):
        validate_production_config(placeholder)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(placeholder), encoding="utf-8")
    with pytest.raises(ValueError, match="placeholder"):
        load_config(str(path))


def test_validated_production_config_loads(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(production_config()), encoding="utf-8")
    config = load_config(str(path))
    assert config.lan_host == "192.168.10.20"
    assert config.remote_domain == "gateway.production.example"


def test_installer_never_copies_example_config_or_overwrites_valid_config():
    install = (HOST_AGENT / "install.sh").read_text(encoding="utf-8")
    assert 'CONFIG_SOURCE=${VORTEX_NETCTL_CONFIG_SOURCE:-}' in install
    assert '[[ -e "$CONFIG_PATH" ]] && validate_config "$CONFIG_PATH"' in install
    assert 'Preserving existing validated production config' in install
    assert 'Refusing to install config.example.json' in install
    assert '"$SCRIPT_DIR/config.example.json"' not in install
    assert 'install -o root -g vortex-netctl -m 0640 "$CONFIG_SOURCE" "$CONFIG_PATH"' in install