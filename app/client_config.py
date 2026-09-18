from __future__ import annotations

import sys
from pathlib import Path

from .models import Device


def build_client_config(device: Device, settings: dict) -> dict:
    host_agent_root = Path(__file__).resolve().parents[1] / "host-agent"
    if str(host_agent_root) not in sys.path:
        sys.path.insert(0, str(host_agent_root))
    from vortex_netctl.client_template import render_client_template

    lan, remote = settings["lan"], settings["remote"]
    return render_client_template(
        host_agent_root / "client-template.json",
        uuid=device.uuid,
        lan_host=lan["host"],
        lan_port=lan["port"],
        lan_ssids=lan.get("ssids") or [lan["ssid"]],
        remote_domain=remote["domain"],
        remote_port=remote["port"],
    )