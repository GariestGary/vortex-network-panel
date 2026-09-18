from __future__ import annotations
from .models import Device

def build_client_config(device: Device, settings: dict) -> dict:
    lan, remote = settings["lan"], settings["remote"]
    return {"log":{"level":"warn"}, "inbounds":[{"type":"tun","tag":"tun-in","auto_route":True,"strict_route":True,"stack":"mixed"}],
      "outbounds":[
        {"type":"vmess","tag":"vortex-lan","server":lan["host"],"server_port":lan["port"],"uuid":device.uuid,"security":"auto"},
        {"type":"vmess","tag":"vortex-remote","server":remote["domain"],"server_port":remote["port"],"uuid":device.uuid,"security":"auto","tls":{"enabled":True,"server_name":remote["domain"]},"transport":{"type":"ws","path":"/","headers":{"Host":remote["domain"]}}}
      ],
      "route":{"rules":[{"wifi_ssid":[lan["ssid"]],"outbound":"vortex-lan"}],"final":"vortex-remote"}}

