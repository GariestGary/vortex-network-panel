import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path("host-agent")))
from vortex_netctl.config import AgentConfig, load_config
from vortex_netctl.controller import Controller
from vortex_netctl.system import CommandResult, System
from vortex_netctl.transaction import CRITICAL, SUCCESS, TransactionManager


class HealthySystem:
    def __init__(self, restarts=(0,)):
        self.restarts = list(restarts)

    def restart_singbox(self):
        return CommandResult(self.restarts.pop(0) if self.restarts else 0)

    def singbox_healthy(self):
        return True


def test_transaction_serializes_concurrent_mutations(tmp_path):
    target = tmp_path / "state.json"
    target.write_text('{"values": []}\n', encoding="utf-8")
    tx = TransactionManager(HealthySystem(), tmp_path / "backups", tmp_path / "lock")
    barrier = threading.Barrier(2)
    results = []

    def mutate(value):
        barrier.wait()
        result = tx.apply_mutation(
            target,
            f"add:{value}",
            lambda current: {"values": current["values"] + [value]},
            lambda _: CommandResult(0),
        )
        results.append(result.result)

    threads = [threading.Thread(target=mutate, args=(value,)) for value in ("one", "two")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == [SUCCESS, SUCCESS]
    assert sorted(json.loads(target.read_text(encoding="utf-8"))["values"]) == ["one", "two"]


def test_failed_rollback_is_critical_and_restores_original_file(tmp_path):
    target = tmp_path / "config.json"
    target.write_text('{"old": true}\n', encoding="utf-8")
    result = TransactionManager(HealthySystem(restarts=(1, 1)), tmp_path / "backups", tmp_path / "lock").apply_json(
        target, {"new": True}, "test", lambda _: CommandResult(0)
    )
    assert result.result == CRITICAL
    assert json.loads(target.read_text(encoding="utf-8")) == {"old": True}


def test_system_run_handles_timeout_and_missing_executable(monkeypatch):
    system = System()
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired(args[0], kwargs["timeout"])))
    assert system.run(("/fixed",), 1).code == 124
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("missing")))
    assert system.run(("/fixed",), 1).code == 127


def test_malformed_production_config_fails_closed(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_config(str(path))


class RuleValidationSystem:
    def __init__(self):
        self.checked = []

    def check_config(self, path):
        self.checked.append(json.loads(Path(path).read_text(encoding="utf-8")))
        return CommandResult(0)


def test_rule_candidate_validation_requires_exact_managed_reference(tmp_path):
    singbox = tmp_path / "sing-box.json"
    rule_path = tmp_path / "force-vpn.json"
    candidate = tmp_path / "candidate.json"
    rule_path.write_text('{"version": 5, "rules": []}', encoding="utf-8")
    candidate.write_text('{"version": 5, "rules": [{"domain": ["example.com"]}]}', encoding="utf-8")
    singbox.write_text(json.dumps({"route": {"rule_set": [{"type": "local", "path": str(rule_path)}]}}), encoding="utf-8")
    system = RuleValidationSystem()
    controller = Controller(AgentConfig(sing_box_config=singbox, force_vpn=rule_path, force_direct=tmp_path / "force-direct.json", backups=tmp_path / "backups", lock_file=tmp_path / "lock", lan_host="192.168.10.20", lan_port=2443, lan_ssid="ProductionNetwork", remote_domain="gateway.production.example", remote_port=443), system)
    assert controller._validate_rule_candidate("vpn", candidate).code == 0
    assert system.checked[0]["route"]["rule_set"][0]["path"] == str(candidate)
    singbox.write_text(json.dumps({"route": {"rule_set": []}}), encoding="utf-8")
    assert controller._validate_rule_candidate("vpn", candidate).code == 1


class StatusSystem:
    def service_active(self, unit):
        return unit == "sing-box.service"

    def listeners(self):
        return CommandResult(0, "127.0.0.1:2081\n192.168.10.20:2443\n")

    def docker_inspect(self, container):
        return CommandResult(127)

    def awg(self):
        return CommandResult(127)

    def ip_check(self, socks, endpoint):
        return CommandResult(1 if socks else 0, "" if socks else "203.0.113.7\n")


def test_status_degrades_when_docker_or_vpn_is_unavailable(tmp_path):
    singbox = tmp_path / "sing-box.json"
    singbox.write_text(json.dumps({"inbounds": [
        {"tag": "remote-vmess", "listen": "127.0.0.1", "listen_port": 2081, "users": []},
        {"tag": "lan-vmess", "listen": "192.168.10.20", "listen_port": 2443, "users": []},
    ]}), encoding="utf-8")
    controller = Controller(AgentConfig(sing_box_config=singbox, backups=tmp_path / "backups", lock_file=tmp_path / "lock", lan_host="192.168.10.20", lan_port=2443, lan_ssid="ProductionNetwork", remote_domain="gateway.production.example", remote_port=443), StatusSystem())
    status = controller.get_status()
    assert status["egress"] == [{"name": "DIRECT", "ip": "203.0.113.7"}, {"name": "VPN", "ip": "N/A"}]
    assert any(item["name"] == "amnezia-vpn" and item["value"] == "Down" for item in status["dependencies"])


def test_diagnostics_logs_are_redacted_and_bounded(tmp_path):
    class LogSystem:
        def journal(self, unit):
            return CommandResult(0, "token=top-secret\nhttps://user:pass@example.test/path\n" + "x" * 700 + "\n")

    controller = Controller(AgentConfig(backups=tmp_path / "backups", lock_file=tmp_path / "lock", lan_host="192.168.10.20", lan_port=2443, lan_ssid="ProductionNetwork", remote_domain="gateway.production.example", remote_port=443), LogSystem())
    logs = controller.logs()
    output = "\n".join(logs)
    assert "top-secret" not in output and "user:pass" not in output
    assert "[REDACTED]" in output and "[REDACTED_URI_CREDENTIALS]" in output
    assert len(output.encode("utf-8")) <= 8192