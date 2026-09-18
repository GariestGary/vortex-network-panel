import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.adapter import ProductionAdapter

sys.path.insert(0, str(Path("host-agent")))
from vortex_netctl.config import AgentConfig
from vortex_netctl.controller import Controller
from vortex_netctl.system import CommandResult


PRODUCTION_INGRESS = [
    {"name": "Remote", "endpoint": "127.0.0.1:2081", "protocol": "VMess / WS / Remote relay"},
    {"name": "LAN", "endpoint": "192.168.10.20:2443", "protocol": "VMess TCP"},
    {"name": "Docker", "endpoint": "172.20.0.1:8080", "protocol": "Mixed"},
    {"name": "Host local", "endpoint": "127.0.0.1:2080", "protocol": "Mixed"},
]


class FakeProductionRpc:
    def __init__(self, logs=None, backups=None, diagnostics_error=False, backups_error=False):
        self.logs, self.backups = logs or ["host-agent: healthy"], backups if backups is not None else []
        self.diagnostics_error, self.backups_error = diagnostics_error, backups_error

    def call(self, method, params=None):
        if method == "get_status":
            return {
                "core": [{"name": "sing-box", "value": "Running"}],
                "dependencies": [],
                "egress": [],
                "ingress": PRODUCTION_INGRESS,
                "settings": {"lan": {"host": "192.168.10.20", "port": 2443, "ssid": "ProductionNetwork"}, "remote": {"domain": "gateway.production.example", "port": 443}},
            }
        if method == "get_devices":
            return {"devices": [{"name": "remote-client", "enabled": True}], "warnings": []}
        if method == "get_recent_logs":
            if self.diagnostics_error:
                raise ConnectionError("agent unavailable")
            return self.logs
        if method == "list_backups":
            if self.backups_error:
                raise ConnectionError("agent unavailable")
            return self.backups
        raise AssertionError(f"Unexpected RPC method: {method}")


def production_adapter(**kwargs):
    adapter = ProductionAdapter()
    adapter.rpc = FakeProductionRpc(**kwargs)
    return adapter


def test_production_adapter_uses_agent_state_without_mock_values():
    status = production_adapter().status()
    assert status["ingress"] == PRODUCTION_INGRESS
    rendered = json.dumps(status)
    for value in ("192.168.50.10", "ExampleWiFi", "gateway.example.com"):
        assert value not in rendered


def test_production_diagnostics_gracefully_handles_agent_error_without_mock_reads():
    diagnostics = production_adapter(diagnostics_error=True).diagnostics()
    assert diagnostics == {"status": {"egress": []}, "logs": [], "error": "Unavailable"}


def test_production_backups_empty_state_and_no_toggle_control(monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    import app.main as main

    monkeypatch.setattr(main, "adapter", production_adapter())
    client = TestClient(main.app)
    backups = client.get("/backups")
    assert backups.status_code == 200
    assert "No backups yet." in backups.text
    assert "mock adapter retains" not in backups.text
    assert "Restore" not in backups.text
    devices = client.get("/devices")
    assert devices.status_code == 200
    assert "remote-client" in devices.text
    assert "Disable" not in devices.text


def test_production_overview_ingress_and_diagnostics_render_typed_agent_data(monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    import app.main as main

    monkeypatch.setattr(main, "adapter", production_adapter())
    client = TestClient(main.app)
    for path in ("/", "/ingress"):
        response = client.get(path)
        assert response.status_code == 200
        assert "192.168.10.20:2443" in response.text
        assert "192.168.50.10" not in response.text
        assert "Host local" in response.text
    diagnostics = client.get("/diagnostics")
    assert diagnostics.status_code == 200
    assert "host-agent: healthy" in diagnostics.text


class IngressSystem:
    def service_active(self, unit):
        return True

    def listeners(self):
        return CommandResult(0, "\n".join(item["endpoint"] for item in PRODUCTION_INGRESS))


def test_host_agent_ingress_is_read_from_singbox_inbounds(tmp_path):
    config_path = tmp_path / "sing-box.json"
    config_path.write_text(json.dumps({"inbounds": [
        {"tag": "remote-vmess", "listen": "127.0.0.1", "listen_port": 2081, "users": []},
        {"tag": "lan-vmess", "listen": "192.168.10.20", "listen_port": 2443, "users": []},
        {"tag": "docker-egress", "listen": "172.20.0.1", "listen_port": 8080},
        {"tag": "local-test", "listen": "127.0.0.1", "listen_port": 2080},
    ]}), encoding="utf-8")
    config = AgentConfig(sing_box_config=config_path, backups=tmp_path / "backups", lock_file=tmp_path / "lock", lan_host="192.168.10.20", lan_port=2443, lan_ssid="ProductionNetwork", remote_domain="gateway.production.example", remote_port=443)
    controller = Controller(config, IngressSystem())
    assert controller.get_ingress() == PRODUCTION_INGRESS
    assert controller._singbox_healthy()