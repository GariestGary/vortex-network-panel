from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os


REQUIRED_PRODUCTION_FIELDS = ("lan_host", "lan_port", "remote_domain", "remote_port")


@dataclass(frozen=True)
class AgentConfig:
    sing_box_config: Path = Path("/etc/sing-box/config.json")
    force_vpn: Path = Path("/etc/sing-box/rules/force-vpn.json")
    force_direct: Path = Path("/etc/sing-box/rules/force-direct.json")
    force_hyvpn: Path = Path("/etc/sing-box/rules/force-hyvpn.json")
    hyvpn_state_dir: Path = Path("/var/lib/hyvpn-vortex")
    backups: Path = Path("/var/lib/vortex-netctl/backups")
    lock_file: Path = Path("/run/lock/vortex-netctl.lock")
    socket_path: str = "/run/vortex-netctl/vortex-netctl.sock"
    subscription_socket_path: str = "/run/vortex-subscription/subscription.sock"
    subscription_store: Path = Path("/var/lib/vortex-netctl/subscriptions.json")
    client_template: Path = Path("/etc/vortex-netctl/client-template.json")
    client_template_versions: Path = Path("/var/lib/vortex-netctl/client-template-versions")
    lan_host: str = ""
    lan_port: int = 0
    lan_ssid: str = ""
    lan_ssids: tuple[str, ...] = ()
    remote_domain: str = ""
    remote_port: int = 0
    ip_endpoint: str = "https://api.ipify.org"

    @property
    def resolved_lan_ssids(self) -> tuple[str, ...]:
        if self.lan_ssids:
            return self.lan_ssids
        return (self.lan_ssid,) if self.lan_ssid else ()

    def rule_path(self, target: str) -> Path:
        if target == "vpn":
            return self.force_vpn
        if target == "hyvpn":
            return self.force_hyvpn
        if target == "direct":
            return self.force_direct
        raise ValueError("Unknown routing target")


def normalized_lan_ssids(raw: dict[str, object]) -> tuple[str, ...]:
    has_legacy = "lan_ssid" in raw
    has_plural = "lan_ssids" in raw
    if has_legacy and has_plural:
        raise ValueError("Production config must use either lan_ssid or lan_ssids, not both")
    if has_plural:
        values = raw["lan_ssids"]
        if not isinstance(values, list) or not values:
            raise ValueError("Production config field lan_ssids must be a non-empty list")
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError("Production config field lan_ssids must contain non-empty strings")
        normalized = tuple(value.strip() for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("Production config field lan_ssids must not contain duplicates")
        return normalized
    if has_legacy and isinstance(raw["lan_ssid"], str) and raw["lan_ssid"].strip():
        return (raw["lan_ssid"].strip(),)
    raise ValueError("Production config must include a non-empty lan_ssids list or legacy lan_ssid")


def config_has_placeholders(raw: dict[str, object]) -> bool:
    ssids = normalized_lan_ssids(raw)
    domain = raw.get("remote_domain")
    return any(ssid.casefold().startswith("example") for ssid in ssids) or (
        isinstance(domain, str) and domain.casefold().endswith(".example.com")
    )


def validate_production_config(raw: dict[str, object]) -> None:
    missing = [key for key in REQUIRED_PRODUCTION_FIELDS if key not in raw]
    if missing:
        raise ValueError(f"Production config is missing required fields: {', '.join(missing)}")
    ssids = normalized_lan_ssids(raw)
    if config_has_placeholders(raw):
        raise ValueError("Production config contains example placeholder values")
    if "client_template" in raw and (not isinstance(raw["client_template"], str) or not Path(raw["client_template"]).is_absolute()):
        raise ValueError("Production config field client_template must be an absolute path")
    for key in ("lan_host", "remote_domain"):
        if not isinstance(raw[key], str) or not raw[key].strip():
            raise ValueError(f"Production config field {key} must be a non-empty string")
    for key in ("lan_port", "remote_port"):
        if not isinstance(raw[key], int) or not 1 <= raw[key] <= 65535:
            raise ValueError(f"Production config field {key} must be an integer TCP port")
    if not ssids:
        raise ValueError("Production config field lan_ssids must not be empty")


def load_config(path: str | None = None) -> AgentConfig:
    path = path or os.getenv("VORTEX_AGENT_CONFIG", "/etc/vortex-netctl/config.json")
    file = Path(path)
    if not file.exists():
        raise ValueError(f"Production config does not exist: {file}")
    raw = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Production config must be a JSON object")
    validate_production_config(raw)
    known = {key: raw[key] for key in AgentConfig.__dataclass_fields__ if key in raw}
    known["lan_ssids"] = normalized_lan_ssids(raw)
    known.pop("lan_ssid", None)
    for key in ("sing_box_config", "force_vpn", "force_hyvpn", "force_direct", "hyvpn_state_dir", "backups", "lock_file", "client_template", "client_template_versions", "subscription_store"):
        if key in known:
            known[key] = Path(known[key])
    return AgentConfig(**known)