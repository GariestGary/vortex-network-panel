from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json, os

@dataclass(frozen=True)
class AgentConfig:
    sing_box_config: Path = Path("/etc/sing-box/config.json")
    force_vpn: Path = Path("/etc/sing-box/rules/force-vpn.json")
    force_direct: Path = Path("/etc/sing-box/rules/force-direct.json")
    backups: Path = Path("/var/lib/vortex-netctl/backups")
    lock_file: Path = Path("/run/lock/vortex-netctl.lock")
    socket_path: str = "/run/vortex-netctl/vortex-netctl.sock"
    lan_host: str = "192.168.50.10"
    lan_port: int = 2080
    lan_ssid: str = "ExampleWiFi"
    remote_domain: str = "gateway.example.com"
    remote_port: int = 443
    ip_endpoint: str = "https://api.ipify.org"
    def rule_path(self, target: str) -> Path:
        if target == "vpn": return self.force_vpn
        if target == "direct": return self.force_direct
        raise ValueError("Unknown routing target")

def load_config(path: str | None = None) -> AgentConfig:
    path = path or os.getenv("VORTEX_AGENT_CONFIG", "/etc/vortex-netctl/config.json")
    file = Path(path)
    if not file.exists(): return AgentConfig()
    raw = json.loads(file.read_text(encoding="utf-8"))
    known = {k: raw[k] for k in AgentConfig.__dataclass_fields__ if k in raw}
    for key in ("sing_box_config", "force_vpn", "force_direct", "backups", "lock_file"):
        if key in known: known[key] = Path(known[key])
    return AgentConfig(**known)

