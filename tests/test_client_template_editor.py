import json
import os
import stat
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path("host-agent")))
from vortex_netctl.config import AgentConfig
from vortex_netctl.controller import Controller
from vortex_netctl.protocol import parse_request
from vortex_netctl.system import CommandResult

import app.main as main


SOURCE_TEMPLATE = Path("host-agent/client-template.json")
UUID = "00000000-0000-4000-8000-000000000001"


class CheckSystem:
    def __init__(self, code=0): self.code = code; self.checked = []
    def check_config(self, path): self.checked.append(json.loads(Path(path).read_text(encoding="utf-8"))); return CommandResult(self.code)


def subject(tmp_path, system=None):
    path = tmp_path / "client-template.json"
    path.write_bytes(SOURCE_TEMPLATE.read_bytes())
    os.chmod(path, 0o640)
    return Controller(AgentConfig(client_template=path, client_template_versions=tmp_path / "versions", backups=tmp_path / "backups", lock_file=tmp_path / "lock", lan_host="192.168.1.66", lan_port=2082, lan_ssids=("Wind",), remote_domain="volt.example.test", remote_port=443), system or CheckSystem())


def changed_template(controller, level="debug"):
    data = json.loads(controller.get_client_template()["template"])
    data["log"]["level"] = level
    return json.dumps(data, indent=2) + "\n"


def test_get_validate_and_invalid_candidates_do_not_change_current_template(tmp_path):
    control = subject(tmp_path)
    current = control.get_client_template()
    assert current["revision"] == control.template_versions.revision(current["template"])
    assert control.validate_client_template("{")["valid"] is False
    assert control.validate_client_template(current["template"].replace("__VORTEX_UUID__", "__VORTEX_UNKNOWN__"))["valid"] is False
    assert control.get_client_template() == current


def test_generated_singbox_check_rejects_candidate_without_writing(tmp_path):
    control = subject(tmp_path, CheckSystem(code=1))
    current = control.get_client_template()
    result = control.validate_client_template(changed_template(control))
    assert result == {"valid": False, "message": "Generated client config failed sing-box validation"}
    assert control.get_client_template() == current


def test_save_is_atomic_preserves_mode_and_creates_previous_version(tmp_path):
    control = subject(tmp_path)
    current = control.get_client_template()
    candidate = changed_template(control)
    saved = control.save_client_template(candidate, current["revision"])
    assert saved["valid"] and control.get_client_template()["template"] == candidate
    assert stat.S_IMODE(control.config.client_template.stat().st_mode) == 0o640
    versions = control.list_client_template_versions()
    assert len(versions) == 1
    assert control.template_versions.load(versions[0]["id"]) == current["template"]
    assert not list(tmp_path.glob(".vortex-*"))


def test_failed_save_and_conflict_leave_current_template_unchanged(tmp_path):
    control = subject(tmp_path)
    current = control.get_client_template()
    assert control.save_client_template("{", current["revision"])["valid"] is False
    assert control.get_client_template() == current
    control.save_client_template(changed_template(control), current["revision"])
    with pytest.raises(ValueError, match="changed; reload"):
        control.save_client_template(changed_template(control, "trace"), current["revision"])


def test_restore_backs_up_current_and_rejects_corrupted_history(tmp_path):
    control = subject(tmp_path)
    original = control.get_client_template()
    control.save_client_template(changed_template(control, "debug"), original["revision"])
    previous = control.list_client_template_versions()[0]
    current = control.get_client_template()
    control.restore_client_template_version(previous["id"], current["revision"])
    assert control.get_client_template()["template"] == original["template"]
    assert len(control.list_client_template_versions()) == 2
    bad = control.config.client_template_versions / "20260101T000000Z-0000000000000000.json"
    bad.write_text('{"id":"20260101T000000Z-0000000000000000","template":"{}","sha256":"bad"}', encoding="utf-8")
    with pytest.raises(ValueError): control.restore_client_template_version(bad.stem, control.get_client_template()["revision"])


def test_retention_and_generation_reload_after_save(tmp_path):
    control = subject(tmp_path)
    for index in range(22):
        current = control.get_client_template()
        control.save_client_template(changed_template(control, f"debug{index}"), current["revision"])
    assert len(control.list_client_template_versions()) == 20
    assert control._client_config("DEVICE", UUID)["log"]["level"] == "debug21"


def test_template_rpc_is_typed_and_subscription_protocol_has_no_admin_method():
    request, params = parse_request(b'{"version":1,"request_id":"abcdefgh","method":"validate_client_template","params":{"template":"{}"}}')
    assert request.method == "validate_client_template" and params.template == "{}"
    with pytest.raises(ValueError):
        parse_request(b'{"version":1,"request_id":"abcdefgh","method":"save_client_template","params":{"template":"{}","path":"/etc/passwd","expected_revision":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}}')


class EditorAdapter:
    def __init__(self): self.template = '{"safe":"<tag>"}\n'; self.revision = "a" * 64
    def client_template(self): return {"template": self.template, "revision": self.revision}
    def client_template_versions(self): return [{"id":"20260101T000000Z-0000000000000000", "timestamp":"20260101T000000Z", "sha256":"b" * 64}]
    def validate_client_template(self, template): return {"valid": False, "message":"<script>unsafe</script>"}
    def save_client_template(self, template, expected_revision): return {"valid": True, "message":"Client template saved", "revision": "b" * 64}
    def restore_client_template_version(self, version_id, expected_revision): return {"valid": True, "message":"Client template saved", "revision": "b" * 64}


def test_editor_page_escapes_template_and_mutations_require_csrf(monkeypatch):
    monkeypatch.setattr(main, "adapter", EditorAdapter())
    client = TestClient(main.app)
    page = client.get("/settings/client-config")
    assert page.status_code == 200 and "&lt;tag&gt;" in page.text
    assert client.post("/settings/client-config/save", data={"template":"{}", "expected_revision":"a" * 64}).status_code == 403
    assert client.post("/settings/client-config/restore/20260101T000000Z-0000000000000000", data={"expected_revision":"a" * 64}).status_code == 403


def test_compose_panel_has_no_host_config_mount():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    panel = compose.split("  subscription:", 1)[0]
    assert "/etc/vortex-netctl" not in panel and "/run/vortex-netctl:/run/vortex-netctl:ro" in panel