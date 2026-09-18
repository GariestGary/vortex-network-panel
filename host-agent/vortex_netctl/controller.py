from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import ipaddress, json, os, re, tempfile
from .config import AgentConfig
from .rules import parse_ruleset, mutate_ruleset, normalize_domain
from .singbox import analyze_devices, mutate_device, assert_device_diff_allowed, validate_existing_name
from .system import System
from .transaction import TransactionManager, TransactionResult, SUCCESS

LISTENERS={"local":"127.0.0.1:2080","remote":"127.0.0.1:2081","lan":"192.168.50.10:2080","docker":"172.21.0.1:2088","vpn_socks":"127.0.0.1:18890"}
ANSI=re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

class Controller:
    def __init__(self, config:AgentConfig, system:System): self.config,self.system=config,system; self.tx=TransactionManager(system,config.backups,config.lock_file)
    def _config(self): return json.loads(self.config.sing_box_config.read_text(encoding="utf-8"))
    def _rules(self,target): return json.loads(self.config.rule_path(target).read_text(encoding="utf-8"))
    def get_devices(self, client_config_for: str | None = None):
        state=analyze_devices(self._config())
        if client_config_for:
            validate_existing_name(client_config_for)
            # Explicit action only; never included in list/status responses.
            users={u["name"]:u["uuid"] for u in next(x for x in self._config()["inbounds"] if x.get("tag")=="remote-vmess")["users"]}
            if client_config_for not in users: raise ValueError("Device not found")
            return {"client_config":self._client_config(client_config_for,users[client_config_for])}
        return state
    def _client_config(self,name,uuid):
        return {"log":{"level":"warn"},"inbounds":[{"type":"tun","tag":"tun-in","auto_route":True,"strict_route":True,"stack":"mixed"}],"outbounds":[{"type":"vmess","tag":"vortex-lan","server":self.config.lan_host,"server_port":self.config.lan_port,"uuid":uuid,"security":"auto"},{"type":"vmess","tag":"vortex-remote","server":self.config.remote_domain,"server_port":self.config.remote_port,"uuid":uuid,"security":"auto","tls":{"enabled":True,"server_name":self.config.remote_domain},"transport":{"type":"ws","path":"/","headers":{"Host":self.config.remote_domain}}}],"route":{"rules":[{"wifi_ssid":[self.config.lan_ssid],"outbound":"vortex-lan"}],"final":"vortex-remote"}}
    def mutate_device(self, operation,name):
        current=self._config(); candidate=mutate_device(current,operation,name); assert_device_diff_allowed(current,candidate)
        return self.tx.apply_json(self.config.sing_box_config,candidate,f"{operation}_device:{name}",self.system.check_config).__dict__
    def get_routing(self):
        vpn,vpnu=parse_ruleset(self._rules("vpn")); direct,directu=parse_ruleset(self._rules("direct"))
        return {"vpn":vpn,"direct":direct,"warnings":{"vpn":vpnu,"direct":directu},"priority":"force-direct before force-vpn"}
    def _validate_rule_candidate(self,target,candidate_path:Path):
        config=self._config(); config=deepcopy(config); expected=str(self.config.rule_path(target))
        for entry in config.get("route",{}).get("rule_set",[]):
            if entry.get("type")=="local" and entry.get("path")==expected: entry["path"]=str(candidate_path)
        fd,temp=tempfile.mkstemp(prefix=".vortex-rule-check-",suffix=".json",dir=self.config.sing_box_config.parent); os.close(fd)
        try:
            Path(temp).write_text(json.dumps(config),encoding="utf-8")
            return self.system.check_config(Path(temp))
        finally: Path(temp).unlink(missing_ok=True)
    def mutate_routing(self,target,domain,remove):
        domain=normalize_domain(domain); other="direct" if target=="vpn" else "vpn"
        if not remove and domain in self.get_routing()[other]: raise ValueError(f"Domain already exists in force-{other}; explicit conflict is not allowed")
        path=self.config.rule_path(target); candidate=mutate_ruleset(self._rules(target),domain,remove)
        return self.tx.apply_json(path,candidate,f"{'remove' if remove else 'add'}_{target}:{domain}",lambda p:self._validate_rule_candidate(target,p)).__dict__
    def get_ingress(self): return [{"name":"Remote","endpoint":"127.0.0.1:2081","protocol":"VMess / WS / Remote relay"},{"name":"LAN","endpoint":"192.168.50.10:2080","protocol":"VMess TCP"},{"name":"Docker","endpoint":"172.21.0.1:2088","protocol":"Mixed"},{"name":"Host local","endpoint":"127.0.0.1:2080","protocol":"Mixed"}]
    def get_status(self):
        listening=self.system.listeners().stdout
        core=[{"name":"sing-box","value":"Running" if self.system.service_active("sing-box.service") else "Down"}]
        dependencies=[{"name":"amnezia-socks listener","value":"Healthy" if "127.0.0.1:18890" in listening else "Degraded"},{"name":"amnezia-vpn","value":"Healthy" if self.system.docker_inspect("amnezia-vpn").code==0 else "Down"},{"name":"amnezia-socks","value":"Healthy" if self.system.docker_inspect("amnezia-socks").code==0 else "Down"},{"name":"awg0 (amnezia-vpn)","value":"Healthy" if self.system.awg().code==0 else "Down"},{"name":"Remote relay","value":"Healthy" if self.system.service_active("tuna-volt.service") else "Down"}]
        return {"core":core,"dependencies":dependencies,"listeners":[{"name":name,"endpoint":endpoint,"value":"Listening" if endpoint in listening else "Unavailable"} for name,endpoint in LISTENERS.items()],"egress":[{"name":"DIRECT","ip":self.test_ip(False)},{"name":"VPN","ip":self.test_ip(True)}],"ingress":self.get_ingress(),"settings":{"lan":{"host":self.config.lan_host,"port":self.config.lan_port,"ssid":self.config.lan_ssid},"remote":{"domain":self.config.remote_domain,"port":self.config.remote_port}}}
    def test_ip(self,socks:bool):
        result=self.system.ip_check(socks,self.config.ip_endpoint); value=result.stdout.strip()
        try: return str(ipaddress.ip_address(value))
        except ValueError: return "N/A"
    def test_destination(self,domain):
        domain=normalize_domain(domain).removeprefix("*.")
        dns=self.system.run(("/usr/bin/getent","ahosts",domain),8)
        tcp=self.system.run(("/usr/bin/curl","--silent","--output","/dev/null","--max-time","8","--connect-timeout","5",f"https://{domain}"),10)
        return {"destination":domain,"dns":"reachable" if dns.code==0 else "failed","tls":"reachable" if tcp.code==0 else "failed","routing":"Not inferred; no reliable sing-box route inspection API configured."}
    def logs(self):
        lines=[]
        for unit in ("sing-box.service","tuna-volt.service","vortex-netctl.service"):
            lines += [ANSI.sub("",line)[:1000] for line in self.system.journal(unit).stdout.splitlines()]
        return lines[-150:]
    def backups(self):
        output=[]
        for meta in sorted(self.config.backups.glob("*.meta.json"),reverse=True):
            data=json.loads(meta.read_text(encoding="utf-8")); output.append({k:data.get(k) for k in ("id","timestamp","operation","result")})
        return output
    def restore(self,backup_id):
        if not re.fullmatch(r"[0-9TZ-]+-[a-f0-9]{8}",backup_id): raise ValueError("Invalid backup id")
        path=self.config.backups/f"{backup_id}.json"
        candidate=json.loads(path.read_text(encoding="utf-8")); return self.tx.apply_json(self.config.sing_box_config,candidate,f"restore:{backup_id}",self.system.check_config).__dict__
