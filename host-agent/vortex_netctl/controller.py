from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import ipaddress
import logging
import socket
import json
import os
import re
import time
import tempfile

from .client_template import ClientTemplateError, render_client_template, template_uses_placeholder
from .template_versions import TemplateVersionError, TemplateVersions
from .config import AgentConfig
from .rules import mutate_ruleset, normalize_domain, parse_ruleset
from .singbox import analyze_devices, assert_device_diff_allowed, mutate_device, validate_existing_name
from .system import CommandResult, System
from .subscriptions import SubscriptionStore
from .transaction import TransactionManager


INGRESS_SPECS = (
    ("Remote", "remote-vmess", "VMess / WS / Remote relay"),
    ("LAN", "lan-vmess", "VMess TCP"),
    ("Docker", "docker-egress", "Mixed"),
    ("Host local", "local-test", "Mixed"),
)
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
SENSITIVE_LOG_VALUE = re.compile(r"(?i)\b(?:authorization|bearer|token|secret|password|private[_ -]?key)\b(?:\s*[:=]|\s+)\S+")
URI_CREDENTIALS = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s/@:]+:[^\s/@]+@")


class Controller:
    def __init__(self, config: AgentConfig, system: System):
        self.config, self.system = config, system
        self.tx = TransactionManager(system, config.backups, config.lock_file, self._singbox_healthy)
        self.subscriptions = SubscriptionStore(config.subscription_store)
        self.template_versions = TemplateVersions(config.client_template_versions)

    def _config(self):
        return json.loads(self.config.sing_box_config.read_text(encoding="utf-8"))

    def _rules(self, target):
        return json.loads(self.config.rule_path(target).read_text(encoding="utf-8"))

    def _inbound_endpoint(self, config: dict, tag: str) -> str | None:
        matches = [item for item in config.get("inbounds", []) if item.get("tag") == tag]
        if len(matches) != 1:
            return None
        inbound = matches[0]
        host, port = inbound.get("listen"), inbound.get("listen_port")
        if isinstance(host, str) and host and isinstance(port, int) and 1 <= port <= 65535:
            return f"{host}:{port}"
        return None

    def _ingress(self, config: dict) -> list[dict]:
        ingress = []
        for name, tags, protocol in INGRESS_SPECS:
            endpoint = self._inbound_endpoint(config, tags)
            ingress.append({"name": name, "endpoint": endpoint or "Unavailable", "protocol": protocol})
        return ingress

    def _singbox_healthy(self) -> bool:
        if not self.system.service_active("sing-box.service"):
            return False
        expected = [item["endpoint"] for item in self._ingress(self._config()) if item["endpoint"] != "Unavailable"]
        listening = self.system.listeners().stdout
        return all(endpoint in listening for endpoint in expected)
    def _device_uuids(self) -> dict[str, str]:
        config = self._config()
        state = analyze_devices(config)
        remote = {user["name"]: user["uuid"] for user in next(item for item in config["inbounds"] if item.get("tag") == "remote-vmess")["users"]}
        return {device["name"]: remote[device["name"]] for device in state["devices"]}

    def migrate_subscriptions(self) -> None:
        self.subscriptions.synchronize(set(self._device_uuids()))

    def get_devices(self, client_config_for: str | None = None):
        if client_config_for:
            name = validate_existing_name(client_config_for)
            devices = self._device_uuids()
            if name not in devices:
                raise ValueError("Device not found")
            return {"client_config": self._client_config(name, devices[name])}
        state = analyze_devices(self._config())
        names = {device["name"] for device in state["devices"]}
        for device in state["devices"]:
            device["subscription_status"] = self.subscriptions.status_for(device["name"], names)
        return state

    def get_subscription_token(self, name: str) -> str:
        name = validate_existing_name(name)
        return self.subscriptions.token_for(name, set(self._device_uuids()))

    def rotate_subscription_token(self, name: str) -> str:
        name = validate_existing_name(name)
        return self.subscriptions.rotate(name, set(self._device_uuids()))

    def revoke_subscription_token(self, name: str) -> None:
        name = validate_existing_name(name)
        self.subscriptions.revoke(name, set(self._device_uuids()))

    def _template_revision(self, content: str) -> str:
        return self.template_versions.revision(content)

    def get_client_template(self) -> dict:
        content = self.config.client_template.read_text(encoding="utf-8")
        return {"template": content, "revision": self._template_revision(content)}

    def _validate_client_template(self, content: str) -> dict:
        if len(content.encode("utf-8")) > 131072:
            return {"valid": False, "message": "Client template exceeds the size limit"}
        fd, temporary = tempfile.mkstemp(prefix=".vortex-template-check-", suffix=".json", dir=self.config.client_template.parent)
        os.close(fd)
        template_path = Path(temporary)
        generated_path = None
        try:
            template_path.write_text(content, encoding="utf-8")
            generated = render_client_template(template_path, uuid="00000000-0000-4000-8000-000000000001", lan_host="192.0.2.10", lan_port=2082, lan_ssids=("VORTEX-VALIDATION",), remote_domain="validation.example.invalid", remote_port=443)
            fd, generated_temporary = tempfile.mkstemp(prefix=".vortex-template-generated-", suffix=".json", dir=self.config.client_template.parent)
            os.close(fd)
            generated_path = Path(generated_temporary)
            generated_path.write_text(json.dumps(generated), encoding="utf-8")
            if self.system.check_config(generated_path).code != 0:
                return {"valid": False, "message": "Generated client config failed sing-box validation"}
            return {"valid": True, "message": "Template is valid"}
        except (ClientTemplateError, json.JSONDecodeError, ValueError) as exc:
            return {"valid": False, "message": str(exc)}
        finally:
            template_path.unlink(missing_ok=True)
            if generated_path:
                generated_path.unlink(missing_ok=True)

    def validate_client_template(self, content: str) -> dict:
        return self._validate_client_template(content)

    def _parse_client_template_for_save(self, content: str) -> dict:
        if len(content.encode("utf-8")) > 131072:
            return {"valid": False, "message": "Client template exceeds the size limit"}
        try:
            template = json.loads(content)
        except json.JSONDecodeError:
            return {"valid": False, "message": "Client template JSON is invalid"}
        if not isinstance(template, dict):
            return {"valid": False, "message": "Client template must be a JSON object"}
        return {"valid": True, "message": "Client template is valid JSON"}
    def _save_client_template_locked(self, content: str, expected_revision: str) -> dict:
        current = self.config.client_template.read_text(encoding="utf-8")
        if self._template_revision(current) != expected_revision:
            raise ValueError("Client template changed; reload before saving")
        result = self._parse_client_template_for_save(content)
        if not result["valid"]:
            return result
        source_stat = self.config.client_template.stat()
        self.template_versions.preserve(current)
        self.tx._atomic(self.config.client_template, content.encode("utf-8"), source_stat)
        final = self._parse_client_template_for_save(self.config.client_template.read_text(encoding="utf-8"))
        if not final["valid"]:
            self.tx._atomic(self.config.client_template, current.encode("utf-8"), source_stat)
            raise ValueError("Saved client template failed verification")
        return {"valid": True, "message": "Client template saved", "revision": self._template_revision(content)}

    def save_client_template(self, content: str, expected_revision: str) -> dict:
        with self.tx._exclusive_lock():
            return self._save_client_template_locked(content, expected_revision)

    def list_client_template_versions(self) -> list[dict]:
        return self.template_versions.list()

    def restore_client_template_version(self, version_id: str, expected_revision: str) -> dict:
        with self.tx._exclusive_lock():
            return self._save_client_template_locked(self.template_versions.load(version_id), expected_revision)
    def subscription_config(self, token: str) -> dict:
        devices = self._device_uuids()
        name = self.subscriptions.device_for_token(token, set(devices))
        return self._client_config(name, devices[name])
    def _resolve_remote_ipv4(self) -> str:
        try:
            return str(ipaddress.IPv4Address(self.config.remote_domain))
        except ipaddress.AddressValueError:
            pass
        try:
            records = socket.getaddrinfo(self.config.remote_domain, None, socket.AF_INET, socket.SOCK_STREAM)
        except OSError as exc:
            logging.getLogger("vortex_netctl.controller").warning("configured remote domain IPv4 resolution failed")
            raise ValueError("Configured remote domain could not be resolved to IPv4") from exc
        for record in records:
            try:
                return str(ipaddress.IPv4Address(record[4][0]))
            except (IndexError, ipaddress.AddressValueError):
                continue
        logging.getLogger("vortex_netctl.controller").warning("configured remote domain returned no usable IPv4 address")
        raise ValueError("Configured remote domain could not be resolved to IPv4")
    def _client_config(self, name, uuid):
        remote_ip = self._resolve_remote_ipv4() if template_uses_placeholder(self.config.client_template, "__VORTEX_REMOTE_IP__") else None
        generated = render_client_template(
            self.config.client_template,
            uuid=uuid,
            lan_host=self.config.lan_host,
            lan_port=self.config.lan_port,
            lan_ssids=self.config.resolved_lan_ssids,
            remote_domain=self.config.remote_domain,
            remote_port=self.config.remote_port,
            remote_ip=remote_ip,
        )
        fd, temp = tempfile.mkstemp(prefix=".vortex-client-check-", suffix=".json", dir=self.config.client_template.parent)
        os.close(fd)
        try:
            Path(temp).write_text(json.dumps(generated), encoding="utf-8")
            if self.system.check_config(Path(temp)).code != 0:
                raise ValueError("Generated client config failed sing-box validation")
        finally:
            Path(temp).unlink(missing_ok=True)
        return generated

    def mutate_device(self, operation, name):
        def prepare(current):
            candidate = mutate_device(current, operation, name)
            assert_device_diff_allowed(current, candidate)
            return candidate

        result = self.tx.apply_mutation(self.config.sing_box_config, f"{operation}_device:{name}", prepare, self.system.check_config).__dict__
        self.migrate_subscriptions()
        return result

    def get_routing(self):
        vpn, vpn_warnings = parse_ruleset(self._rules("vpn"))
        hyvpn, hyvpn_warnings = parse_ruleset(self._rules("hyvpn"))
        direct, direct_warnings = parse_ruleset(self._rules("direct"))
        return {"vpn": vpn, "hyvpn": hyvpn, "direct": direct, "warnings": {"vpn": vpn_warnings, "hyvpn": hyvpn_warnings, "direct": direct_warnings}, "priority": "force-direct before force-hyvpn before force-vpn"}

    def _validate_rule_candidate(self, target, candidate_path: Path):
        config = deepcopy(self._config())
        expected = str(self.config.rule_path(target))
        replacements = 0
        for entry in config.get("route", {}).get("rule_set", []):
            if entry.get("type") == "local" and entry.get("path") == expected:
                entry["path"] = str(candidate_path)
                replacements += 1
        if replacements != 1:
            return CommandResult(1, stderr="Expected exactly one managed local rule-set reference")
        fd, temp = tempfile.mkstemp(prefix=".vortex-rule-check-", suffix=".json", dir=self.config.sing_box_config.parent)
        os.close(fd)
        try:
            Path(temp).write_text(json.dumps(config), encoding="utf-8")
            return self.system.check_config(Path(temp))
        finally:
            Path(temp).unlink(missing_ok=True)

    def _hyvpn_state(self):
        root = self.config.hyvpn_state_dir
        try: profiles = json.loads((root / "profiles.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError): profiles = []
        safe = [{key: item.get(key) for key in ("id", "remarks", "routingMode", "serverDescription")} for item in profiles if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("routingMode") == "full-tunnel"] if isinstance(profiles, list) else []
        try: selected = (root / "selected-profile").read_text(encoding="utf-8").strip()
        except OSError: selected = ""
        try: status = json.loads((root / "status.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError): status = {"status": "unavailable"}
        status = {key: status[key] for key in ("status", "profileId", "remarks", "error") if isinstance(status, dict) and isinstance(status.get(key), str)}
        return {"available": bool(safe), "selectedProfile": selected or None, "profiles": safe, "status": status}

    def get_hyvpn(self): return self._hyvpn_state()

    def _atomic_text(self, path: Path, value: str):
        path.parent.mkdir(parents=True, exist_ok=True); fd, temporary = tempfile.mkstemp(prefix=".hyvpn-selection-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out: out.write(value); out.flush(); os.fsync(out.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)

    def _wait_for_hyvpn(self, profile_id):
        for _ in range(20):
            state = self._hyvpn_state()
            if self.system.docker_inspect("hyvpn-gateway").code == 0 and state["status"].get("status") == "connected" and state["status"].get("profileId") == profile_id: return True
            time.sleep(1)
        return False

    def set_hyvpn_profile(self, profile_id):
        state = self._hyvpn_state()
        if not any(item["id"] == profile_id for item in state["profiles"]): raise ValueError("Unknown or non-full-tunnel HYVPN profile")
        previous = state["selectedProfile"]
        if not previous: raise ValueError("Current HYVPN selection is unavailable; refusing unsafe switch")
        target = self.config.hyvpn_state_dir / "selected-profile"
        with self.tx._exclusive_lock():
            self._atomic_text(target, profile_id + "\n")
            if self.system.restart_hyvpn_gateway().code == 0 and self._wait_for_hyvpn(profile_id): return {"result": "SUCCESS", "profileId": profile_id}
            self._atomic_text(target, previous + "\n")
            rollback = self.system.restart_hyvpn_gateway().code == 0 and self._wait_for_hyvpn(previous)
            return {"result": "APPLY_FAILED_ROLLED_BACK" if rollback else "APPLY_FAILED_ROLLBACK_FAILED", "profileId": previous, "requestedProfileId": profile_id}

    def mutate_routing(self, target, domain, remove):
        domain = normalize_domain(domain)
        others = tuple(candidate for candidate in ("direct", "hyvpn", "vpn") if candidate != target)
        path = self.config.rule_path(target)

        def prepare(current):
            for other in others:
                other_domains, _ = parse_ruleset(self._rules(other))
                if not remove and domain in other_domains:
                    raise ValueError(f"Domain already exists in force-{other}; explicit conflict is not allowed")
            return mutate_ruleset(current, domain, remove)

        return self.tx.apply_mutation(path, f"{'remove' if remove else 'add'}_{target}:{domain}", prepare, lambda candidate_path: self._validate_rule_candidate(target, candidate_path)).__dict__

    def get_ingress(self):
        return self._ingress(self._config())

    def get_status(self):
        config = self._config()
        ingress = self._ingress(config)
        core = [{"name": "sing-box", "value": "Running" if self.system.service_active("sing-box.service") else "Down"}]
        dependencies = [{"name": "amnezia-socks listener", "value": "Healthy" if "127.0.0.1:18890" in self.system.listeners().stdout else "Degraded"}, {"name": "amnezia-vpn", "value": "Healthy" if self.system.docker_inspect("amnezia-vpn").code == 0 else "Down"}, {"name": "amnezia-socks", "value": "Healthy" if self.system.docker_inspect("amnezia-socks").code == 0 else "Down"}, {"name": "awg0 (amnezia-vpn)", "value": "Healthy" if self.system.awg().code == 0 else "Down"}, {"name": "Remote relay", "value": "Healthy" if self.system.service_active("tuna-volt.service") else "Down"}]
        return {"core": core, "dependencies": dependencies, "egress": [{"name": "DIRECT", "ip": self.test_ip(False)}, {"name": "VPN", "ip": self.test_ip(True)}], "ingress": ingress, "settings": {"lan": {"host": self.config.lan_host, "port": self.config.lan_port, "ssid": self.config.resolved_lan_ssids[0], "ssids": list(self.config.resolved_lan_ssids)}, "remote": {"domain": self.config.remote_domain, "port": self.config.remote_port}}}

    def test_ip(self, socks: bool):
        result = self.system.ip_check(socks, self.config.ip_endpoint)
        value = result.stdout.strip()
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            return "N/A"

    def test_destination(self, domain):
        domain = normalize_domain(domain).removeprefix("*.")
        dns = self.system.run(("/usr/bin/getent", "ahosts", domain), 8)
        tcp = self.system.run(("/usr/bin/curl", "--silent", "--output", "/dev/null", "--max-time", "8", "--connect-timeout", "5", f"https://{domain}"), 10)
        return {"destination": domain, "dns": "reachable" if dns.code == 0 else "failed", "tls": "reachable" if tcp.code == 0 else "failed", "routing": "Not inferred; no reliable sing-box route inspection API configured."}

    def logs(self):
        lines = []
        for unit in ("sing-box.service", "tuna-volt.service", "vortex-netctl.service"):
            for line in self.system.journal(unit).stdout.splitlines():
                clean = ANSI.sub("", line)
                clean = URI_CREDENTIALS.sub("[REDACTED_URI_CREDENTIALS]", clean)
                clean = SENSITIVE_LOG_VALUE.sub("[REDACTED]", clean)
                lines.append(clean[:512])
        selected, budget = [], 8192
        for line in reversed(lines):
            size = len(line.encode("utf-8")) + 1
            if size > budget:
                break
            selected.append(line)
            budget -= size
        return list(reversed(selected))

    def backups(self):
        output = []
        for meta in sorted(self.config.backups.glob("*.meta.json"), reverse=True):
            data = json.loads(meta.read_text(encoding="utf-8"))
            output.append({key: data.get(key) for key in ("id", "timestamp", "operation", "result")})
        return output

    def restore(self, backup_id):
        if not re.fullmatch(r"[0-9TZ-]+-[a-f0-9]{8}", backup_id):
            raise ValueError("Invalid backup id")
        path = self.config.backups / f"{backup_id}.json"
        candidate = json.loads(path.read_text(encoding="utf-8"))
        result = self.tx.apply_json(self.config.sing_box_config, candidate, f"restore:{backup_id}", self.system.check_config).__dict__
        self.migrate_subscriptions()
        return result