from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOST_AGENT = ROOT / "host-agent"


def test_production_compose_mounts_runtime_directory_not_socket_inode():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "/run/vortex-netctl:/run/vortex-netctl:ro" in compose
    assert "/run/vortex-netctl/vortex-netctl.sock:/run/vortex-netctl/vortex-netctl.sock" not in compose
    assert "VORTEX_NETCTL_SOCKET: /run/vortex-netctl/vortex-netctl.sock" in compose
    assert "group_add:" in compose
    assert "no-new-privileges:true" in compose
    assert 'cap_drop: ["ALL"]' in compose


def test_agent_socket_recreation_is_compatible_with_panel_reconnects():
    agent = (HOST_AGENT / "vortex_netctl" / "agent.py").read_text(encoding="utf-8")
    adapter = (ROOT / "app" / "adapter.py").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "prepare_socket(config.socket_path)" in agent
    assert "prepare_socket(config.subscription_socket_path)" in agent
    assert "os.chmod(config.socket_path, 0o660)" in agent
    assert "os.chmod(config.subscription_socket_path, 0o660)" in agent
    assert "with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:" in adapter
    assert "subscription service mounts only `/run/vortex-subscription`" in readme


def test_installer_restarts_and_health_checks_agent_on_every_update():
    install = (HOST_AGENT / "install.sh").read_text(encoding="utf-8")
    assert "systemctl daemon-reload" in install
    assert "systemctl enable vortex-netctl.service" in install
    assert "systemctl enable --now vortex-netctl.service" not in install
    assert "systemctl restart vortex-netctl.service" in install
    assert "systemctl is-active --quiet vortex-netctl.service" in install
    assert "failed to become active after installation" in install


def test_socket_directory_and_socket_permissions_remain_restricted():
    unit = (HOST_AGENT / "vortex-netctl.service").read_text(encoding="utf-8")
    tmpfiles = (HOST_AGENT / "tmpfiles.conf").read_text(encoding="utf-8")
    install = (HOST_AGENT / "install.sh").read_text(encoding="utf-8")
    assert "Group=vortex-netctl" in unit
    assert "UMask=0007" in unit
    assert "d /run/vortex-netctl 0750 root vortex-netctl -" in tmpfiles
    assert "d /run/vortex-subscription 0750 root vortex-netctl -" in tmpfiles
    assert "install -d -o root -g vortex-netctl -m 0750" in install