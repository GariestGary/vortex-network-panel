import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path("host-agent")))
from vortex_netctl.config import AgentConfig
from vortex_netctl.controller import Controller
from vortex_netctl.system import CommandResult
from vortex_netctl.transaction import CRITICAL, ROLLED_BACK, SUCCESS, TransactionManager


class ReadinessSystem:
    def __init__(self, health, restarts=(0,)):
        self.health = iter(health)
        self.restarts = list(restarts)
        self.restart_calls = 0

    def restart_singbox(self):
        self.restart_calls += 1
        return CommandResult(self.restarts.pop(0) if self.restarts else 0)

    def singbox_healthy(self):
        return next(self.health, False)


def metadata(backups):
    return json.loads(next(backups.glob("*.meta.json")).read_text(encoding="utf-8"))


def test_readiness_poll_waits_for_listeners_without_rollback(tmp_path, monkeypatch):
    monkeypatch.setattr("vortex_netctl.transaction.READINESS_POLL_SECONDS", 0)
    target = tmp_path / "rules.json"
    target.write_text('{"version":5,"rules":[]}', encoding="utf-8")
    system = ReadinessSystem([False, False, True])
    result = TransactionManager(system, tmp_path / "backups", tmp_path / "lock").apply_json(
        target, {"version": 5, "rules": [{"domain": ["example.com"]}]}, "add_direct:example.com", lambda _: CommandResult(0)
    )
    assert result.result == SUCCESS
    assert system.restart_calls == 1
    assert json.loads(target.read_text(encoding="utf-8"))["rules"] == [{"domain": ["example.com"]}]
    assert metadata(tmp_path / "backups")["result"] == SUCCESS


def test_unready_candidate_rolls_back_and_metadata_is_not_success(tmp_path, monkeypatch):
    monkeypatch.setattr("vortex_netctl.transaction.READINESS_TIMEOUT_SECONDS", 0)
    target = tmp_path / "rules.json"
    target.write_text('{"version":5,"rules":[]}', encoding="utf-8")
    system = ReadinessSystem([False, True])
    result = TransactionManager(system, tmp_path / "backups", tmp_path / "lock").apply_json(
        target, {"version": 5, "rules": [{"domain": ["example.com"]}]}, "add_direct:example.com", lambda _: CommandResult(0)
    )
    assert result.result == ROLLED_BACK
    assert system.restart_calls == 2
    assert json.loads(target.read_text(encoding="utf-8")) == {"version": 5, "rules": []}
    assert metadata(tmp_path / "backups")["result"] == ROLLED_BACK


def test_failed_rollback_records_critical_final_result(tmp_path, monkeypatch):
    monkeypatch.setattr("vortex_netctl.transaction.READINESS_TIMEOUT_SECONDS", 0)
    target = tmp_path / "rules.json"
    target.write_text('{"version":5,"rules":[]}', encoding="utf-8")
    system = ReadinessSystem([False], restarts=(0, 1))
    result = TransactionManager(system, tmp_path / "backups", tmp_path / "lock").apply_json(
        target, {"version": 5, "rules": [{"domain": ["example.com"]}]}, "add_direct:example.com", lambda _: CommandResult(0)
    )
    assert result.result == CRITICAL
    assert metadata(tmp_path / "backups")["result"] == CRITICAL


def test_success_requires_post_apply_candidate_invariant(tmp_path):
    target = tmp_path / "rules.json"
    target.write_text('{"version":5,"rules":[]}', encoding="utf-8")
    system = ReadinessSystem([True, True])
    tx = TransactionManager(system, tmp_path / "backups", tmp_path / "lock")
    tx._candidate_persisted = lambda path, candidate: False
    result = tx.apply_json(target, {"version": 5, "rules": [{"domain": ["example.com"]}]}, "add_direct:example.com", lambda _: CommandResult(0))
    assert result.result == ROLLED_BACK
    assert json.loads(target.read_text(encoding="utf-8")) == {"version": 5, "rules": []}


class RoutingSystem:
    def check_config(self, path):
        return CommandResult(0)

    def restart_singbox(self):
        return CommandResult(0)


def test_successful_routing_add_persists_current_rule_file(tmp_path):
    rules = tmp_path / "force-direct.json"
    other = tmp_path / "force-vpn.json"
    singbox = tmp_path / "sing-box.json"
    rules.write_text('{"version":5,"rules":[]}', encoding="utf-8")
    other.write_text('{"version":5,"rules":[]}', encoding="utf-8")
    singbox.write_text(json.dumps({"route": {"rule_set": [{"type": "local", "path": str(rules)}, {"type": "local", "path": str(other)}]}}), encoding="utf-8")
    config = AgentConfig(sing_box_config=singbox, force_direct=rules, force_vpn=other, backups=tmp_path / "backups", lock_file=tmp_path / "lock", lan_host="192.168.1.66", lan_port=2082, lan_ssid="WIND", remote_domain="gateway.example", remote_port=443)
    controller = Controller(config, RoutingSystem())
    controller.tx.health_check = lambda: True
    result = controller.mutate_routing("direct", "example.com", False)
    assert result["result"] == SUCCESS
    assert controller.get_routing()["direct"] == ["example.com"]


class RoutingAdapter:
    can_toggle_devices = False
    can_restore_backups = False

    def __init__(self, result=SUCCESS):
        self.result, self.direct = result, []

    def routing(self):
        return {"vpn": [], "direct": self.direct, "warnings": {"vpn": [], "direct": []}}

    def route_change(self, target, domain, remove=False):
        if self.result == SUCCESS:
            if remove:
                self.direct.remove(domain)
            else:
                self.direct.append(domain)
        return {"result": self.result}


def csrf_token(response):
    import re
    return re.search(r"csrf=([^\"]+)", response.text).group(1)


def test_routing_post_redirects_with_success_flash_and_current_rules(monkeypatch):
    import app.main as main

    adapter = RoutingAdapter()
    monkeypatch.setattr(main, "adapter", adapter)
    client = TestClient(main.app)
    page = client.get("/routing")
    response = client.post(f"/routing/direct?csrf={csrf_token(page)}", data={"domain": "example.com"}, follow_redirects=True)
    assert "example.com added to Force Direct" in response.text
    assert "example.com" in response.text
    assert "Remove" in response.text


def test_routing_post_shows_rollback_failure_flash(monkeypatch):
    import app.main as main

    monkeypatch.setattr(main, "adapter", RoutingAdapter(ROLLED_BACK))
    client = TestClient(main.app)
    page = client.get("/routing")
    response = client.post(f"/routing/direct?csrf={csrf_token(page)}", data={"domain": "example.com"}, follow_redirects=True)
    assert "Previous configuration was restored." in response.text
