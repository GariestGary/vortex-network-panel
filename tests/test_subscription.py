import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main
import app.subscription as subscription

sys.path.insert(0, str(Path("host-agent")))
from vortex_netctl.config import AgentConfig
from vortex_netctl.controller import Controller
from vortex_netctl.protocol import parse_subscription_request
from vortex_netctl.system import CommandResult


UUID_A = "00000000-0000-4000-8000-000000000001"
UUID_B = "00000000-0000-4000-8000-000000000002"


class CheckSystem:
    def check_config(self, path):
        return CommandResult(0)

    def restart_singbox(self):
        return CommandResult(0)

    def service_active(self, unit):
        return True

    def listeners(self):
        return CommandResult(0)


def controller(tmp_path):
    state = {"inbounds": [
        {"tag": "remote-vmess", "users": [{"name": "DEVICE_A", "uuid": UUID_A}, {"name": "DEVICE_B", "uuid": UUID_B}]},
        {"tag": "lan-vmess", "users": [{"name": "DEVICE_A", "uuid": UUID_A}, {"name": "DEVICE_B", "uuid": UUID_B}]},
    ]}
    path = tmp_path / "sing-box.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    config = AgentConfig(
        sing_box_config=path,
        subscription_store=tmp_path / "subscriptions.json",
        backups=tmp_path / "backups",
        lock_file=tmp_path / "lock",
        client_template=Path("host-agent/client-template.json"),
        lan_host="192.168.1.66",
        lan_port=2082,
        lan_ssids=("Wind_5",),
        remote_domain="volt.jetstream.su",
        remote_port=443,
    )
    return Controller(config, CheckSystem()), path


def test_existing_devices_receive_unique_persistent_subscription_tokens(tmp_path):
    subject, _ = controller(tmp_path)
    subject.migrate_subscriptions()
    first = subject.get_subscription_token("DEVICE_A")
    second = subject.get_subscription_token("DEVICE_B")
    assert first != second
    assert len(first) >= 43 and len(second) >= 43
    store = tmp_path / "subscriptions.json"
    assert store.stat().st_mode & 0o777 == 0o600
    subject.rotate_subscription_token("DEVICE_A")
    assert store.stat().st_mode & 0o777 == 0o600
    restarted, _ = controller(tmp_path)
    assert restarted.get_subscription_token("DEVICE_B") == second


def test_device_delete_invalidates_token_and_recreate_gets_a_new_one(tmp_path):
    subject, _ = controller(tmp_path)
    old = subject.get_subscription_token("DEVICE_A")
    subject.mutate_device("delete", "DEVICE_A")
    with pytest.raises(ValueError):
        subject.subscription_config(old)
    subject.mutate_device("add", "DEVICE_A")
    assert subject.get_subscription_token("DEVICE_A") != old


def test_vmess_and_subscription_rotations_are_independent(tmp_path):
    subject, _ = controller(tmp_path)
    token = subject.get_subscription_token("DEVICE_A")
    subject.mutate_device("rotate", "DEVICE_A")
    assert subject.get_subscription_token("DEVICE_A") == token
    uuid_after_vmess_rotation = subject.subscription_config(token)["outbounds"][0]["uuid"]
    new_token = subject.rotate_subscription_token("DEVICE_A")
    assert subject.subscription_config(new_token)["outbounds"][0]["uuid"] == uuid_after_vmess_rotation


def test_corrupted_subscription_store_fails_closed_without_regeneration(tmp_path):
    subject, _ = controller(tmp_path)
    subject.get_subscription_token("DEVICE_A")
    store = tmp_path / "subscriptions.json"
    store.write_text('{"version":1,"devices":', encoding="utf-8")
    restarted, _ = controller(tmp_path)
    with pytest.raises(ValueError, match="Subscription state"):
        restarted.migrate_subscriptions()


def test_subscription_token_selects_only_its_device_config(tmp_path):
    subject, _ = controller(tmp_path)
    token_a = subject.get_subscription_token("DEVICE_A")
    config_a = subject.subscription_config(token_a)
    assert all(outbound["uuid"] == UUID_A for outbound in config_a["outbounds"])
    with pytest.raises(ValueError):
        subject.subscription_config("not-a-token")


def test_revoke_and_rotation_invalidate_old_token_without_rotating_vmess_uuid(tmp_path):
    subject, state_path = controller(tmp_path)
    old = subject.get_subscription_token("DEVICE_A")
    subject.revoke_subscription_token("DEVICE_A")
    with pytest.raises(ValueError):
        subject.subscription_config(old)
    new = subject.rotate_subscription_token("DEVICE_A")
    assert new != old
    assert all(outbound["uuid"] == UUID_A for outbound in subject.subscription_config(new)["outbounds"])
    stored = json.loads(state_path.read_text(encoding="utf-8"))
    assert stored["inbounds"][0]["users"][0]["uuid"] == UUID_A
    assert stored["inbounds"][1]["users"][0]["uuid"] == UUID_A


def test_restricted_subscription_protocol_rejects_administrative_commands():
    for body in (
        b'{"version":1,"request_id":"abcdefgh","method":"delete_device","params":{"name":"DEVICE_A"}}',
        b'{"version":1,"request_id":"abcdefgh","token":"x","method":"get_status"}',
    ):
        with pytest.raises(ValueError):
            parse_subscription_request(body)


class FakeSubscriptionAdapter:
    def client_config(self, token):
        if token != "valid-token":
            raise ValueError("not found")
        return {"outbounds": [{"tag": "proxy"}]}


def subscription_client(monkeypatch):
    monkeypatch.setattr(subscription, "adapter", FakeSubscriptionAdapter())
    return TestClient(subscription.app)


def test_subscription_http_returns_json_or_not_found(monkeypatch):
    client = subscription_client(monkeypatch)
    response = client.get("/s/valid-token")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/s/wrong-token").status_code == 404
    for path in ("/", "/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_admin_panel_remains_available():
    assert TestClient(main.app).get("/devices").status_code == 200


def test_subscription_service_mounts_only_restricted_socket_and_disables_access_log():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    subscription_service = compose.split("  subscription:\n", 1)[1]
    assert '"127.0.0.1:9081:9081"' in subscription_service
    assert "/run/vortex-subscription:/run/vortex-subscription:ro" in subscription_service
    assert "/run/vortex-netctl" not in subscription_service
    assert "VORTEX_SUBSCRIPTION_TOKEN" not in subscription_service
    assert "VORTEX_SUBSCRIPTION_DEVICE" not in subscription_service
    assert "--no-access-log" in subscription_service