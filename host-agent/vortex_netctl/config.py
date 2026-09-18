from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os


REQUIRED_PRODUCTION_FIELDS = ("lan_host", "lan_port", "lan_ssid", "remote_domain", "remote_port")


@dataclass(frozen=True)
class AgentConfig:
    sing_box_config: Path = Path("/etc/sing-box/config.json")
    force_vpn: Path = Path("/etc/sing-box/rules/force-vpn.json")
    force_direct: Path = Path("/etc/sing-box/rules/force-direct.json")
    backups: Path = Path("/var/lib/vortex-netctl/backups")
    lock_file: Path = Path("/run/lock/vortex-netctl.lock")
    socket_path: str = "/run/vortex-netctl/vortex-netctl.sock"
    lan_host: str = ""
    lan_port: int = 0
    lan_ssid: str = ""
    remote_domain: str = ""
    remote_port: int = 0
    ip_endpoint: str = "https://api.ipify.org"

    def rule_path(self, target: str) -> Path:
        if target == "vpn":
            return self.force_vpn
        if target == "direct":
            return self.force_direct
        raise ValueError("Unknown routing target")


def config_has_placeholders(raw: dict[str, object]) -> bool:
    ssid = raw.get("lan_ssid")
    domain = raw.get("remote_domain")
    return (
        isinstance(ssid, str) and ssid.casefold().startswith("example")
    ) or (
        isinstance(domain, str) and domain.casefold().endswith(".example.com")
    )


def validate_production_config(raw: dict[str, object]) -> None:
    missing = [key for key in REQUIRED_PRODUCTION_FIELDS if key not in raw]
    if missing:
        raise ValueError(f"Production config is missing required fields: {', '.join(missing)}")
    if config_has_placeholders(raw):
        raise ValueError("Production config contains example placeholder values")
    for key in ("lan_host", "lan_ssid", "remote_domain"):
        if not isinstance(raw[key], str) or not raw[key].strip():
            raise ValueError(f"Production config field {key} must be a non-empty string")
    for key in ("lan_port", "remote_port"):
        if not isinstance(raw[key], int) or not 1 <= raw[key] <= 65535:
            raise ValueError(f"Production config field {key} must be an integer TCP port")


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
    for key in ("sing_box_config", "force_vpn", "force_direct", "backups", "lock_file"):
        if key in known:
            known[key] = Path(known[key])
    return AgentConfig(**known)