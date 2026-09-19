from fastapi.testclient import TestClient

import app.main as main
import app.subscription as subscription


class FakeAdapter:
    def client_config(self, device_name):
        if device_name != "LAPTOP_ALPHA":
            raise ValueError("Device not found")
        return {"log": {"level": "warn"}, "outbounds": [{"tag": "proxy"}]}


def subscription_client(monkeypatch):
    monkeypatch.setenv("VORTEX_SUBSCRIPTION_TOKEN", "test-token")
    monkeypatch.setenv("VORTEX_SUBSCRIPTION_DEVICE", "LAPTOP_ALPHA")
    monkeypatch.setattr(subscription, "adapter", FakeAdapter())
    return TestClient(subscription.app)


def test_valid_subscription_token_returns_client_config_json(monkeypatch):
    response = subscription_client(monkeypatch).get("/s/test-token")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"log": {"level": "warn"}, "outbounds": [{"tag": "proxy"}]}


def test_invalid_subscription_token_returns_not_found(monkeypatch):
    response = subscription_client(monkeypatch).get("/s/wrong-token")
    assert response.status_code == 404


def test_subscription_service_has_no_other_routes(monkeypatch):
    client = subscription_client(monkeypatch)
    for path in ("/", "/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_admin_panel_remains_available():
    response = TestClient(main.app).get("/devices")
    assert response.status_code == 200


def test_missing_subscription_device_returns_not_found(monkeypatch):
    monkeypatch.setenv("VORTEX_SUBSCRIPTION_TOKEN", "test-token")
    monkeypatch.setenv("VORTEX_SUBSCRIPTION_DEVICE", "missing-device")
    monkeypatch.setattr(subscription, "adapter", FakeAdapter())
    assert TestClient(subscription.app).get("/s/test-token").status_code == 404


def test_subscription_service_is_local_and_keeps_panel_hardening():
    compose = open("docker-compose.yml", encoding="utf-8").read()
    subscription_service = compose.split("  subscription:\n", 1)[1]
    assert '"127.0.0.1:9081:9081"' in subscription_service
    assert '"0.0.0.0:9081:9081"' not in subscription_service
    assert "/run/vortex-netctl:/run/vortex-netctl:ro" in subscription_service
    assert "VORTEX_NETCTL_GID" in subscription_service
    assert "read_only: true" in subscription_service
    assert "/tmp:mode=1777" in subscription_service
    assert "no-new-privileges:true" in subscription_service
    assert 'cap_drop: ["ALL"]' in subscription_service