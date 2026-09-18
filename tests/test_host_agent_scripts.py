from pathlib import Path


HOST_AGENT = Path("host-agent")


def test_host_agent_scripts_resolve_local_files_from_their_own_directory():
    for name in ("install.sh", "uninstall.sh"):
        script = (HOST_AGENT / name).read_text(encoding="utf-8")
        assert "set -euo pipefail" in script
        assert 'SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"' in script

    install = (HOST_AGENT / "install.sh").read_text(encoding="utf-8")
    for path in (
        "vortex_netctl",
        "requirements.txt",
        "config.example.json",
        "vortex-netctl.service",
        "tmpfiles.conf",
    ):
        assert f'"$SCRIPT_DIR/{path}"' in install