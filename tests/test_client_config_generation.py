import json
import sys
from pathlib import Path

from app.client_config import build_client_config
from app.models import Device

sys.path.insert(0, str(Path("host-agent")))
from vortex_netctl.config import AgentConfig
from vortex_netctl.controller import Controller
from vortex_netctl.singbox import analyze_devices
from vortex_netctl.system import CommandResult


UUID = "00000000-0000-4000-8000-000000000001"
SETTINGS = {
    "lan": {"host": "192.168.1.66", "port": 2082, "ssid": "WIND"},
    "remote": {"domain": "volt.jetstream.su", "port": 443},
}


def assert_client_route(config):
    assert config["route"]["auto_detect_interface"] is True
    assert config["route"]["rules"] == [{"wifi_ssid": ["WIND"], "action": "route", "outbound": "vortex-lan"}]
    assert config["route"]["final"] == "vortex-remote"
    lan, remote = config["outbounds"]
    assert lan["uuid"] == remote["uuid"] == UUID
    assert remote["tls"]["enabled"] is True
    assert remote["transport"]["type"] == "ws"
    assert remote["transport"]["headers"]["Host"] == "volt.jetstream.su"


def test_mock_client_config_uses_current_route_action_syntax():
    assert_client_route(build_client_config(Device(name="TYPHOON", uuid=UUID), SETTINGS))


def test_production_host_agent_client_config_uses_current_route_action_syntax(tmp_path):
    config = AgentConfig(
        backups=tmp_path / "backups",
        lock_file=tmp_path / "lock",
        lan_host="192.168.1.66",
        lan_port=2082,
        lan_ssid="WIND",
        remote_domain="volt.jetstream.su",
        remote_port=443,
    )
    assert_client_route(Controller(config, object())._client_config("TYPHOON", UUID))


def test_normal_device_list_and_logs_do_not_expose_uuid(tmp_path):
    state = {"inbounds": [
        {"tag": "remote-vmess", "users": [{"name": "TYPHOON", "uuid": UUID}]},
        {"tag": "lan-vmess", "users": [{"name": "TYPHOON", "uuid": UUID}]},
    ]}
    assert UUID not in json.dumps(analyze_devices(state))

    class LogSystem:
        def journal(self, unit):
            return CommandResult(0, "device TYPHOON operation completed")

    config = AgentConfig(backups=tmp_path / "backups", lock_file=tmp_path / "lock", lan_host="192.168.1.66", lan_port=2082, lan_ssid="WIND", remote_domain="volt.jetstream.su", remote_port=443)
    assert UUID not in "\n".join(Controller(config, LogSystem()).logs())