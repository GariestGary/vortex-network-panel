import json, os, sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path("host-agent")))
from vortex_netctl.singbox import analyze_devices, mutate_device, assert_device_diff_allowed
from vortex_netctl.rules import parse_ruleset, mutate_ruleset
from vortex_netctl.protocol import parse_request, MAX_REQUEST_BYTES
from vortex_netctl.transaction import TransactionManager, SUCCESS, VALIDATION_FAILED, ROLLED_BACK
from vortex_netctl.system import CommandResult

def config():
    return {"unknown":{"preserve":True},"inbounds":[{"tag":"remote-vmess","users":[{"name":"ONE","uuid":"11111111-1111-1111-1111-111111111111","alterId":0}]},{"tag":"lan-vmess","users":[{"name":"ONE","uuid":"11111111-1111-1111-1111-111111111111","alterId":0}]}]}

def test_find_tags_add_preserves_unknown_fields():
    before=config(); after=mutate_device(before,"add","NEW_DEVICE")
    assert before["unknown"] == after["unknown"]
    assert [x["name"] for x in after["inbounds"][0]["users"]] == ["ONE","NEW_DEVICE"]
    assert after["inbounds"][0]["users"][1]["uuid"] == after["inbounds"][1]["users"][1]["uuid"]
    assert_device_diff_allowed(before,after)

def test_duplicate_rotate_delete_and_inconsistency():
    with pytest.raises(ValueError): mutate_device(config(),"add","ONE")
    rotated=mutate_device(config(),"rotate","ONE")
    assert rotated["inbounds"][0]["users"][0]["uuid"] == rotated["inbounds"][1]["users"][0]["uuid"]
    assert rotated["inbounds"][0]["users"][0]["uuid"] != config()["inbounds"][0]["users"][0]["uuid"]
    assert not mutate_device(config(),"delete","ONE")["inbounds"][0]["users"]
    broken=config(); broken["inbounds"][1]["users"][0]["uuid"]="22222222-2222-2222-2222-222222222222"
    assert analyze_devices(broken)["warnings"][0]["type"] == "uuid_mismatch"

def test_rules_v5_and_conflict_inputs():
    base={"version":5,"rules":[]}; changed=mutate_ruleset(base,"*.example.com",False)
    assert parse_ruleset(changed)[0] == ["*.example.com"]
    with pytest.raises(ValueError): parse_ruleset({"version":1,"rules":[]})

@pytest.mark.parametrize("body",[b'{"version":1,"request_id":"abcdefgh","method":"exec","params":{}}',b'{"version":2,"request_id":"abcdefgh","method":"get_status","params":{}}',b'{"version":1,"request_id":"abcdefgh","method":"get_status","params":{"path":"/etc/passwd"}}',b'x'* (MAX_REQUEST_BYTES+1)])
def test_rpc_rejects_unknown_or_oversized(body):
    with pytest.raises(ValueError): parse_request(body)

class FakeSystem:
    def __init__(self,check=0,restarts=(0,),active=True): self.check,self.restarts,self.active=check,list(restarts),active
    def check_config(self,path): return CommandResult(self.check)
    def restart_singbox(self): return CommandResult(self.restarts.pop(0) if self.restarts else 0)
    def service_active(self,unit): return self.active

def test_transaction_validation_and_rollback(tmp_path):
    target=tmp_path/"config.json"; target.write_text('{"old":true}\n'); lock=tmp_path/"lock"; backups=tmp_path/"backups"
    failed=TransactionManager(FakeSystem(check=1),backups,lock).apply_json(target,{"new":True},"test",lambda p:CommandResult(1))
    assert failed.result == VALIDATION_FAILED and json.loads(target.read_text())["old"]
    rolled=TransactionManager(FakeSystem(restarts=(1,0)),backups,lock).apply_json(target,{"new":True},"test",lambda p:CommandResult(0))
    assert rolled.result == ROLLED_BACK and json.loads(target.read_text())["old"]

def test_list_response_has_no_uuid():
    payload=analyze_devices(config())
    assert "11111111" not in json.dumps(payload)

class CoreHealthSystem(FakeSystem):
    def listeners(self): return CommandResult(0, "LISTEN 127.0.0.1:2080\nLISTEN 127.0.0.1:2081\nLISTEN 192.168.10.20:2443\nLISTEN 172.21.0.1:2088\n")
    def singbox_healthy(self):
        return self.service_active("sing-box.service") and all(endpoint in self.listeners().stdout for endpoint in ("127.0.0.1:2080","127.0.0.1:2081","192.168.10.20:2443","172.21.0.1:2088"))

def test_core_health_does_not_require_vpn_socks_listener(tmp_path):
    target=tmp_path/"config.json"; target.write_text('{"old":true}\n')
    result=TransactionManager(CoreHealthSystem(),tmp_path/"backups",tmp_path/"lock").apply_json(target,{"new":True},"test",lambda p:CommandResult(0))
    assert result.result == SUCCESS
    assert json.loads(target.read_text()) == {"new":True}