import re

from fastapi.testclient import TestClient

import app.main as main
from app.models import Device


TOKEN_A = "subscription-token-a-should-never-render-in-html"
TOKEN_B = "subscription-token-b-should-never-render-in-html"


class AdminSubscriptionAdapter:
    can_toggle_devices = True
    can_restore_backups = False

    def __init__(self):
        self.uuid = "00000000-0000-4000-8000-000000000001"
        self.tokens = {"DEVICE_A": TOKEN_A, "DEVICE_B": TOKEN_B}
        self.revoked = {"DEVICE_B"}
        self.changed = []

    def devices(self):
        return [
            Device(name="DEVICE_A", uuid=self.uuid, subscription_status="active"),
            Device(name="DEVICE_B", uuid="00000000-0000-4000-8000-000000000002", subscription_status="revoked"),
        ]

    def subscription_token(self, name):
        if name not in self.tokens or name in self.revoked:
            raise ValueError("Subscription token not found")
        return self.tokens[name]

    def rotate_subscription_token(self, name):
        if name not in self.tokens:
            raise ValueError("Device not found")
        self.tokens[name] = f"rotated-{name}-token"
        self.revoked.discard(name)
        return self.tokens[name]

    def revoke_subscription_token(self, name):
        if name not in self.tokens:
            raise ValueError("Device not found")
        self.revoked.add(name)

    def change_device(self, name, action):
        self.changed.append((name, action))
        if action == "rotate":
            self.uuid = "00000000-0000-4000-8000-000000000003"


def client_with_adapter(monkeypatch):
    adapter = AdminSubscriptionAdapter()
    monkeypatch.setattr(main, "adapter", adapter)
    client = TestClient(main.app)
    page = client.get("/devices")
    csrf = re.search(r"csrf=([^\"]+)", page.text).group(1)
    return client, adapter, page, csrf


def test_devices_page_shows_status_without_rendering_tokens(monkeypatch):
    _, _, page, _ = client_with_adapter(monkeypatch)
    assert "Active" in page.text and "Revoked" in page.text
    assert TOKEN_A not in page.text and TOKEN_B not in page.text
    assert "Copy token" in page.text
    assert "Rotate subscription token" in page.text
    assert "Rotate VMess UUID" in page.text


def test_active_token_endpoint_is_no_store_and_revoked_or_missing_is_not_found(monkeypatch):
    client, _, _, _ = client_with_adapter(monkeypatch)
    response = client.get("/devices/DEVICE_A/subscription-token")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"token": TOKEN_A}
    assert client.get("/devices/DEVICE_B/subscription-token").status_code == 404
    assert client.get("/devices/MISSING/subscription-token").status_code == 404


def test_subscription_mutations_require_csrf_and_do_not_change_vmess_uuid(monkeypatch):
    client, adapter, _, csrf = client_with_adapter(monkeypatch)
    assert client.post("/devices/DEVICE_A/subscription/rotate", follow_redirects=False).status_code == 403
    old_token, old_uuid = adapter.tokens["DEVICE_A"], adapter.uuid
    response = client.post("/devices/DEVICE_A/subscription/rotate", headers={"x-csrf-token": csrf}, follow_redirects=False)
    assert response.status_code == 303
    assert adapter.tokens["DEVICE_A"] != old_token
    assert adapter.uuid == old_uuid
    response = client.post("/devices/DEVICE_A/subscription/revoke", headers={"x-csrf-token": csrf}, follow_redirects=False)
    assert response.status_code == 303
    assert adapter.uuid == old_uuid
    assert client.get("/devices/DEVICE_A/subscription-token").status_code == 404


def test_create_token_after_revoke_uses_rotation_without_touching_vmess_uuid(monkeypatch):
    client, adapter, _, csrf = client_with_adapter(monkeypatch)
    uuid = adapter.uuid
    response = client.post("/devices/DEVICE_B/subscription/rotate", headers={"x-csrf-token": csrf}, follow_redirects=False)
    assert response.status_code == 303
    assert "DEVICE_B" not in adapter.revoked
    assert adapter.uuid == uuid
    assert client.get("/devices/DEVICE_B/subscription-token").json() == {"token": "rotated-DEVICE_B-token"}


def test_existing_vmess_control_remains_separate(monkeypatch):
    client, adapter, _, csrf = client_with_adapter(monkeypatch)
    response = client.post("/devices/DEVICE_A/rotate", headers={"x-csrf-token": csrf}, follow_redirects=False)
    assert response.status_code == 303
    assert adapter.changed == [("DEVICE_A", "rotate")]
    assert adapter.tokens["DEVICE_A"] == TOKEN_A
