import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path("host-agent")))
from vortex_netctl.client_template import ClientTemplateError, load_template, render_client_template
from vortex_netctl.config import AgentConfig, load_config
from vortex_netctl.controller import Controller
from vortex_netctl.system import CommandResult


TEMPLATE = Path("host-agent/client-template.json")
UUID = "00000000-0000-4000-8000-000000000001"


def copy_template(tmp_path):
    path = tmp_path / "client-template.json"
    path.write_bytes(TEMPLATE.read_bytes())
    return path


def render(path):
    return render_client_template(path, uuid=UUID, lan_host="192.168.1.66", lan_port=2082, lan_ssids=("Wind_5", "Wind_2_4"), remote_domain="volt.jetstream.su", remote_port=443)


def test_default_template_renders_working_client_config(tmp_path):
    config = render(copy_template(tmp_path))
    lan, remote = config["outbounds"]
    assert lan["uuid"] == remote["uuid"] == UUID
    assert lan["server"] == "192.168.1.66" and lan["server_port"] == 2082
    assert remote["server"] == "volt.jetstream.su" and remote["server_port"] == 443
    assert remote["tls"]["server_name"] == "volt.jetstream.su"
    assert remote["transport"]["headers"]["Host"] == "volt.jetstream.su"
    assert config["route"]["rules"][2]["wifi_ssid"] == ["Wind_5", "Wind_2_4"]
    assert isinstance(config["route"]["rules"][2]["wifi_ssid"], list)
    assert config["dns"]["servers"][1]["inet4_range"] == "198.18.0.0/15"
    assert config["route"]["default_domain_resolver"] == "bootstrap"


def test_template_supports_one_ssid(tmp_path):
    config = render_client_template(copy_template(tmp_path), uuid=UUID, lan_host="192.168.1.66", lan_port=2082, lan_ssids=("Wind_5",), remote_domain="volt.jetstream.su", remote_port=443)
    assert config["route"]["rules"][2]["wifi_ssid"] == ["Wind_5"]


@pytest.mark.parametrize("content, message", [
    ("{", "JSON is invalid"),
    (json.dumps({"value": "__VORTEX_UNKNOWN__"}), "unknown placeholder"),
])
def test_invalid_or_unknown_template_is_rejected(tmp_path, content, message):
    path = tmp_path / "client-template.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ClientTemplateError, match=message):
        render(path)


def test_missing_template_is_rejected_but_optional_placeholders_may_be_absent(tmp_path):
    with pytest.raises(ClientTemplateError, match="unavailable"):
        render(tmp_path / "missing.json")
    path = tmp_path / "remote-only.json"
    path.write_text(json.dumps({"outbounds": [{"uuid": "__VORTEX_UUID__", "server": "__VORTEX_REMOTE_DOMAIN__", "server_port": "__VORTEX_REMOTE_PORT__"}]}), encoding="utf-8")
    config = render(path)
    assert config == {"outbounds": [{"uuid": UUID, "server": "volt.jetstream.su", "server_port": 443}]}


def test_unresolved_placeholder_is_rejected_after_rendering(tmp_path):
    path = copy_template(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["log"]["level"] = "prefix-__VORTEX_UUID__"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ClientTemplateError, match="unresolved placeholder"):
        render(path)


class CheckSystem:
    def __init__(self, code=0):
        self.code = code
        self.checked = []

    def check_config(self, path):
        self.checked.append(json.loads(Path(path).read_text(encoding="utf-8")))
        return CommandResult(self.code)


def controller(tmp_path, system):
    return Controller(AgentConfig(client_template=copy_template(tmp_path), backups=tmp_path / "backups", lock_file=tmp_path / "lock", lan_host="192.168.1.66", lan_port=2082, lan_ssids=("Wind_5", "Wind_2_4"), remote_domain="volt.jetstream.su", remote_port=443), system)


def test_production_generation_runs_singbox_check_and_deletes_temporary_file(tmp_path):
    system = CheckSystem()
    config = controller(tmp_path, system)._client_config("remote-client", UUID)
    assert system.checked == [config]
    assert not list(tmp_path.glob(".vortex-client-check-*.json"))


def test_singbox_check_failure_does_not_return_generated_config_or_uuid_in_error(tmp_path):
    with pytest.raises(ValueError, match="sing-box validation") as error:
        controller(tmp_path, CheckSystem(code=1))._client_config("remote-client", UUID)
    assert UUID not in str(error.value)


def test_template_is_reloaded_for_each_client_config_request(tmp_path):
    system = CheckSystem()
    subject = controller(tmp_path, system)
    first = subject._client_config("remote-client", UUID)
    data = json.loads(subject.config.client_template.read_text(encoding="utf-8"))
    data["log"]["level"] = "debug"
    subject.config.client_template.write_text(json.dumps(data), encoding="utf-8")
    second = subject._client_config("remote-client", UUID)
    assert first["log"]["level"] == "warn"
    assert second["log"]["level"] == "debug"


def test_legacy_config_without_client_template_uses_default_path(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"lan_host": "192.168.1.66", "lan_port": 2082, "lan_ssid": "Wind_5", "remote_domain": "volt.jetstream.su", "remote_port": 443}), encoding="utf-8")
    assert load_config(str(config_path)).client_template == Path("/etc/vortex-netctl/client-template.json")


def test_legacy_device_name_remains_compatible_with_template_generation(tmp_path):
    singbox = tmp_path / "sing-box.json"
    user = {"name": "remote-client", "uuid": UUID}
    singbox.write_text(json.dumps({"inbounds": [{"tag": "remote-vmess", "users": [user]}, {"tag": "lan-vmess", "users": [user]}]}), encoding="utf-8")
    system = CheckSystem()
    subject = controller(tmp_path, system)
    subject.config = AgentConfig(sing_box_config=singbox, client_template=subject.config.client_template, backups=tmp_path / "backups", lock_file=tmp_path / "lock", lan_host="192.168.1.66", lan_port=2082, lan_ssids=("Wind_5",), remote_domain="volt.jetstream.su", remote_port=443)
    assert subject.get_devices("remote-client")["client_config"]["outbounds"][0]["uuid"] == UUID