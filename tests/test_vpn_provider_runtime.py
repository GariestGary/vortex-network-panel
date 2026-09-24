import json, sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path("host-agent")))
from vortex_netctl.config import AgentConfig
from vortex_netctl.controller import Controller
from vortex_netctl.system import CommandResult

class FakeSystem:
    def __init__(self): self.states={"amnezia-vpn":"running","amnezia-socks":"running","hyvpn-gateway":"exited"}; self.commands=[]
    def docker_inspect(self,name): return CommandResult(0,self.states.get(name,"missing")) if name in self.states else CommandResult(1)
    def start_amnezia(self): self.states.update({"amnezia-vpn":"running","amnezia-socks":"running"}); return CommandResult(0)
    def stop_amnezia(self): self.states.update({"amnezia-vpn":"exited","amnezia-socks":"exited"}); return CommandResult(0)
    def start_hyvpn(self): self.states["hyvpn-gateway"]="running healthy"; return CommandResult(0)
    def stop_hyvpn(self): self.states["hyvpn-gateway"]="exited"; return CommandResult(0)
    def provider_socks_healthy(self,provider,endpoint): return self.states["hyvpn-gateway"] == "running healthy" if provider=="hyvpn" else self.states["amnezia-vpn"]=="running"
    def check_config(self,path): return CommandResult(0)
    def restart_singbox(self): return CommandResult(0)
    def service_active(self,name): return True
    def listeners(self): return CommandResult(0,"")

def make(tmp_path):
    vpn=tmp_path/"force-vpn.json"; direct=tmp_path/"force-direct.json"; legacy=tmp_path/"force-hyvpn.json"; state=tmp_path/"hyvpn";state.mkdir()
    for path,domains in ((vpn,["vpn.example"]),(direct,[]),(legacy,["legacy.example","vpn.example"])): path.write_text(json.dumps({"version":5,"rules":[{"domain":[domain]} for domain in domains]}))
    config=tmp_path/"config.json";config.write_text(json.dumps({"outbounds":[{"tag":"vpn","type":"socks","server":"127.0.0.1","server_port":18890},{"tag":"hyvpn","type":"socks","server_port":18891}],"route":{"rule_set":[{"type":"local","tag":"force-hyvpn","path":str(legacy)},{"type":"local","tag":"force-vpn","path":str(vpn)}],"rules":[{"rule_set":"force-hyvpn"}]}}))
    (state/"profiles.json").write_text(json.dumps([{"id":"nl","routingMode":"full-tunnel","remarks":"Netherlands"}]))
    (state/"selected-profile").write_text("nl\n");(state/"status.json").write_text(json.dumps({"status":"connected","profileId":"nl"}))
    ctl=Controller(AgentConfig(sing_box_config=config,force_vpn=vpn,force_direct=direct,force_hyvpn=legacy,hyvpn_state_dir=state,active_vpn_provider=tmp_path/"provider",backups=tmp_path/"backups",lock_file=tmp_path/"lock"),FakeSystem());ctl.tx.health_check=lambda:True;return ctl

def test_migration_removes_legacy_outbound_and_is_idempotent(tmp_path):
    ctl=make(tmp_path);ctl.migrate_legacy_hyvpn();ctl.migrate_legacy_hyvpn();assert set(ctl.get_routing()["vpn"])=={"vpn.example","legacy.example"};assert not any(x.get("tag")=="hyvpn" for x in ctl._config()["outbounds"])

def test_docker_running_semantics(tmp_path):
    ctl=make(tmp_path);assert ctl._provider_running("amnezia");ctl.system.states["amnezia-socks"]="exited";assert not ctl._provider_running("amnezia");del ctl.system.states["amnezia-socks"];assert not ctl._provider_running("amnezia")

def test_switches_provider_and_stops_previous(tmp_path):
    ctl=make(tmp_path);ctl._atomic_text(ctl.config.active_vpn_provider,"amnezia\n");assert ctl.set_vpn_provider("hyvpn")["result"]=="SUCCESS";assert ctl._config()["outbounds"][0]["server_port"]==18891;assert not ctl._provider_running("amnezia") and ctl._provider_running("hyvpn")

def test_hyvpn_state_and_route_mutation_runtime_paths(tmp_path):
    ctl=make(tmp_path);assert ctl.get_hyvpn()["profiles"][0]["id"]=="nl";ctl.migrate_legacy_hyvpn();assert ctl.mutate_routing("vpn","new.example",False)["result"]=="SUCCESS"