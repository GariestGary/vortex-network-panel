from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess


@dataclass
class CommandResult:
    code: int
    stdout: str = ""
    stderr: str = ""


class System:
    """All command lines are fixed by this class; RPC input never reaches argv."""
    def run(self, argv: tuple[str, ...], timeout: int = 10) -> CommandResult:
        try:
            process = subprocess.run(list(argv), shell=False, capture_output=True, text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            return CommandResult(124, (exc.stdout or "")[:8192], (exc.stderr or "timeout")[:8192])
        except OSError as exc:
            return CommandResult(127, "", str(exc)[:8192])
        return CommandResult(process.returncode, process.stdout[:8192], process.stderr[:8192])

    def check_config(self, path: Path) -> CommandResult:
        return self.run(("/usr/bin/sing-box", "check", "-c", str(path)), 20)

    def restart_singbox(self) -> CommandResult:
        return self.run(("/usr/bin/systemctl", "restart", "sing-box.service"), 20)

    def service_active(self, unit: str) -> bool:
        if unit not in {"sing-box.service", "tuna-volt.service", "vortex-netctl.service"}:
            raise ValueError("Unknown fixed unit")
        return self.run(("/usr/bin/systemctl", "is-active", "--quiet", unit), 10).code == 0

    def listeners(self) -> CommandResult:
        return self.run(("/usr/bin/ss", "-lntH"), 10)

    def singbox_healthy(self) -> bool:
        return self.service_active("sing-box.service")

    def docker_inspect(self, container: str) -> CommandResult:
        if container not in {"amnezia-vpn", "amnezia-socks", "hyvpn-gateway"}:
            raise ValueError("Unknown fixed container")
        return self.run(("/usr/bin/docker", "inspect", "--format", "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}", container), 10)
    def restart_hyvpn_gateway(self) -> CommandResult:
        return self.run(("/usr/bin/docker", "restart", "hyvpn-gateway"), 30)


    def awg(self) -> CommandResult:
        return self.run(("/usr/bin/docker", "exec", "amnezia-vpn", "ip", "link", "show", "awg0"), 10)

    def journal(self, unit: str) -> CommandResult:
        if unit not in {"sing-box.service", "tuna-volt.service", "vortex-netctl.service"}:
            raise ValueError("Unknown fixed unit")
        return self.run(("/usr/bin/journalctl", "-u", unit, "-n", "80", "--no-pager", "-o", "short-iso"), 10)

    def ip_check(self, socks: bool, endpoint: str) -> CommandResult:
        argv = ("/usr/bin/curl", "--fail", "--silent", "--show-error", "--max-time", "8", endpoint)
        if socks:
            argv = ("/usr/bin/curl", "--fail", "--silent", "--show-error", "--max-time", "8", "--socks5-hostname", "127.0.0.1:18890", endpoint)
        return self.run(argv, 10)