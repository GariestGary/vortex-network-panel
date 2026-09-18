import json
from pathlib import Path
import pytest
from app.adapter import MockAdapter, RpcAdapter
from app.client_config import build_client_config
from app.models import Device, RouteEntry

@pytest.fixture
def mock_root(tmp_path):
    source=Path("mock")
    for p in source.iterdir(): (tmp_path/p.name).write_bytes(p.read_bytes())
    return tmp_path

def test_add_remove_and_duplicate_device(mock_root):
    a=MockAdapter(mock_root); before=len(a.devices()); device=a.add_device("NEW_DEVICE")
    assert device.name == "NEW_DEVICE" and len(a.devices()) == before + 1
    with pytest.raises(ValueError): a.add_device("NEW_DEVICE")
    a.change_device("NEW_DEVICE","delete")
    assert all(x.name != "NEW_DEVICE" for x in a.devices())

def test_rotate_uuid_and_disable(mock_root):
    a=MockAdapter(mock_root); before=next(x for x in a.devices() if x.name=="LAPTOP_ALPHA").uuid
    after=a.change_device("LAPTOP_ALPHA","rotate").uuid
    assert before != after
    a.change_device("LAPTOP_ALPHA","disable")
    assert not next(x for x in a.devices() if x.name=="LAPTOP_ALPHA").enabled

@pytest.mark.parametrize("value",["example.com","*.example.com"])
def test_domain_validation(value): assert RouteEntry(domain=value).domain == value
@pytest.mark.parametrize("value",["https://example.com","example.com:443","x;id","not a domain"])
def test_bad_domains(value):
    with pytest.raises(ValueError): RouteEntry(domain=value)

def test_routing_and_backup_rotation(mock_root):
    a=MockAdapter(mock_root)
    for i in range(12): a.route_change("vpn",f"example{i}.com")
    assert len(a.backups()) == 10
    assert "example0.com" in a.routing()["vpn"]

def test_client_config(mock_root):
    a=MockAdapter(mock_root); cfg=build_client_config(a.devices()[0],a.status()["settings"])
    lan_rule = next(rule for rule in cfg["route"]["rules"] if "wifi_ssid" in rule)
    assert lan_rule["wifi_ssid"] == ["ExampleWiFi"]
    assert cfg["outbounds"][1]["transport"]["type"] == "ws"
    assert cfg["outbounds"][1]["tls"]["enabled"] is True

def test_mock_fixtures_are_json(mock_root):
    assert MockAdapter(mock_root).status()["egress"][1]["ip"] == "198.51.100.20"

def test_rpc_blocks_arbitrary_command():
    with pytest.raises(ValueError):
        RpcAdapter().call("exec",{"command":"whoami"})
