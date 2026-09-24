import json
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path("host-agent")))
from vortex_netctl.config import AgentConfig
from vortex_netctl.controller import Controller
from vortex_netctl.system import CommandResult
from app.routing_folders import RoutingFolders

class HyvpnSystem:
    def __init__(self, state, fail=False): self.state, self.fail, self.restarts = state, fail, 0
    def docker_inspect(self, name): return CommandResult(0)
    def restart_hyvpn_gateway(self):
        self.restarts += 1
        if not self.fail or self.restarts > 1:
            selected = (self.state / "selected-profile").read_text().strip()
            (self.state / "status.json").write_text(json.dumps({"status":"connected","profileId":selected}))
        return CommandResult(0)

def controller(tmp_path, fail=False):
    state = tmp_path / "state"; state.mkdir()
    (state / "profiles.json").write_text(json.dumps([{"id":"nl","remarks":"Netherlands","routingMode":"full-tunnel","vlessKey":"never returned"},{"id":"fr","remarks":"France","routingMode":"full-tunnel"},{"id":"split","routingMode":"split"}]))
    (state / "selected-profile").write_text("nl\n")
    (state / "status.json").write_text(json.dumps({"status":"connected","profileId":"nl","token":"never returned"}))
    return Controller(AgentConfig(hyvpn_state_dir=state, lock_file=tmp_path/"lock"), HyvpnSystem(state, fail)), state

def test_hyvpn_state_is_sanitized(tmp_path):
    ctl, _ = controller(tmp_path)
    state = ctl.get_hyvpn()
    assert {item["id"] for item in state["profiles"]} == {"nl", "fr"}
    assert all("vlessKey" not in item for item in state["profiles"])
    assert "token" not in state["status"]

def test_hyvpn_rejects_unknown_or_non_full_tunnel(tmp_path):
    ctl, _ = controller(tmp_path)
    with pytest.raises(ValueError): ctl.set_hyvpn_profile("missing")
    with pytest.raises(ValueError): ctl.set_hyvpn_profile("split")

def test_hyvpn_successful_selection(tmp_path, monkeypatch):
    ctl, state = controller(tmp_path); monkeypatch.setattr(ctl, "_wait_for_hyvpn", lambda profile: profile == "nl")
    assert ctl.set_hyvpn_profile("nl")["result"] == "SUCCESS"
    assert state.joinpath("selected-profile").read_text().strip() == "nl"

def test_hyvpn_failed_switch_rolls_back(tmp_path, monkeypatch):
    ctl, state = controller(tmp_path)
    monkeypatch.setattr(ctl, "_wait_for_hyvpn", lambda profile: profile == "nl")
    assert ctl.set_hyvpn_profile("fr")["result"] == "APPLY_FAILED_ROLLED_BACK"
    assert state.joinpath("selected-profile").read_text().strip() == "nl"

def test_routing_folder_migrates_and_has_three_targets(tmp_path):
    path=tmp_path/"folders.json"; path.write_text(json.dumps({"version":1,"vpn":{"folders":[],"assignments":{}},"direct":{"folders":[],"assignments":{}}}))
    folders=RoutingFolders(path); state=folders.state({"vpn":["a.com"],"hyvpn":["b.com"],"direct":["c.com"]})
    assert set(state) == {"vpn","hyvpn","direct"}
    folders.create("hyvpn","Exit"); folder=folders.state({"vpn":[],"hyvpn":["b.com"],"direct":[]})["hyvpn"]["folders"][1]
    folders.move("hyvpn","b.com",folder["id"])
    assert folders.state({"vpn":[],"hyvpn":["b.com"],"direct":[]})["hyvpn"]["assignments"]["b.com"] == folder["id"]