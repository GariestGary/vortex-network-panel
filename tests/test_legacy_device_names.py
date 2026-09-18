import copy
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapter import MockAdapter
from app.models import CreateDeviceRequest, Device
from app.client_config import build_client_config

sys.path.insert(0, str(Path("host-agent")))
from vortex_netctl.protocol import parse_request
from vortex_netctl.singbox import analyze_devices, mutate_device


def production_singbox_with_legacy_name():
    user = {"name": "remote-client", "uuid": "11111111-1111-4111-8111-111111111111"}
    return {
        "inbounds": [
            {"tag": "remote-vmess", "users": [copy.deepcopy(user)]},
            {"tag": "lan-vmess", "users": [copy.deepcopy(user)]},
        ]
    }


def mock_root_with_legacy_name(tmp_path):
    source = Path("mock")
    for path in source.iterdir():
        (tmp_path / path.name).write_bytes(path.read_bytes())
    config_path = tmp_path / "sing-box-config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["devices"].append({
        "name": "remote-client",
        "uuid": "11111111-1111-4111-8111-111111111111",
        "enabled": True,
        "created_at": None,
        "notes": "",
    })
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return tmp_path


def test_existing_legacy_device_is_represented_and_client_config_generates(tmp_path):
    adapter = MockAdapter(mock_root_with_legacy_name(tmp_path))
    legacy = next(device for device in adapter.devices() if device.name == "remote-client")
    assert legacy.legacy_name
    client_config = adapter.client_config("remote-client")
    assert client_config["outbounds"][0]["uuid"] == legacy.uuid


def test_existing_legacy_device_rotate_and_delete_work_in_both_inbounds():
    before = production_singbox_with_legacy_name()
    rotated = mutate_device(before, "rotate", "remote-client")
    remote_uuid = rotated["inbounds"][0]["users"][0]["uuid"]
    lan_uuid = rotated["inbounds"][1]["users"][0]["uuid"]
    assert remote_uuid == lan_uuid
    assert remote_uuid != before["inbounds"][0]["users"][0]["uuid"]
    deleted = mutate_device(rotated, "delete", "remote-client")
    assert not deleted["inbounds"][0]["users"]
    assert not deleted["inbounds"][1]["users"]


def test_existing_lowercase_name_does_not_break_consistency_analysis():
    state = analyze_devices(production_singbox_with_legacy_name())
    assert state["devices"] == [{"name": "remote-client", "enabled": True}]
    assert state["warnings"] == []


def test_create_policy_remains_strict():
    with pytest.raises(ValueError):
        CreateDeviceRequest(name="remote-client")
    assert CreateDeviceRequest(name="HURRICANE").name == "HURRICANE"


def test_rpc_accepts_legacy_lookup_and_mutation_but_rejects_legacy_create():
    for method, params in (
        ("get_devices", {"device_name": "remote-client", "include_client_config": True}),
        ("rotate_device_uuid", {"name": "remote-client"}),
        ("delete_device", {"name": "remote-client"}),
    ):
        request, parsed = parse_request(json.dumps({"version": 1, "request_id": "abcdefgh", "method": method, "params": params}).encode())
        assert request.method == method
        assert getattr(parsed, "name", getattr(parsed, "device_name", None)) == "remote-client"
    with pytest.raises(ValueError):
        parse_request(b'{"version":1,"request_id":"abcdefgh","method":"add_device","params":{"name":"remote-client"}}')


def test_devices_page_displays_legacy_name_and_encoded_config_route(tmp_path, monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    import app.main as main

    monkeypatch.setattr(main, "adapter", MockAdapter(mock_root_with_legacy_name(tmp_path)))
    response = TestClient(main.app).get("/devices")
    assert response.status_code == 200
    assert "remote-client" in response.text
    assert "Legacy name" in response.text
    assert "/devices/remote-client/config" in response.text