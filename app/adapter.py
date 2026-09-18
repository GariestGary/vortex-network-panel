from __future__ import annotations
import json, os, secrets, socket
from pathlib import Path
from .models import Device, RouteEntry, Backup, now

class MockAdapter:
    def __init__(self, root: str | Path | None = None): self.root=Path(root or os.getenv("VORTEX_MOCK_DIR","mock"))
    def _read(self,name): return json.loads((self.root/name).read_text(encoding="utf-8"))
    def _write(self,name,data): (self.root/name).write_text(json.dumps(data,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    def status(self): return self._read("status.json")
    def devices(self): return [Device(**x) for x in self._read("sing-box-config.json")["devices"]]
    def _save_devices(self,devices):
        data=self._read("sing-box-config.json"); data["devices"]=[x.model_dump() for x in devices]; self._write("sing-box-config.json",data)
    def _backup(self,op):
        data=self._read("backups.json"); data.insert(0,Backup(id=now(),timestamp=now(),operation=op,result="Success").model_dump()); self._write("backups.json",data[:10])
    def add_device(self,name):
        devices=self.devices()
        if any(x.name==name for x in devices): raise ValueError("Device name already exists")
        import uuid
        device=Device(name=name,uuid=str(uuid.uuid4()),created_at=now()); self._save_devices(devices+[device]); self._backup(f"Add device {name}"); return device
    def change_device(self,name,action):
        devices=self.devices(); found=next((x for x in devices if x.name==name),None)
        if not found: raise ValueError("Device not found")
        if action=="delete": devices=[x for x in devices if x.name!=name]
        elif action=="rotate":
            import uuid
            found.uuid=str(uuid.uuid4())
        elif action in {"enable","disable"}: found.enabled=action=="enable"
        else: raise ValueError("Unknown device operation")
        self._save_devices(devices); self._backup(f"{action.title()} device {name}"); return found
    def _domains(self,data):
        if data.get("version")!=5: raise ValueError("Mock rule-set must be version 5")
        values=[]
        for rule in data.get("rules",[]):
            if set(rule)=={"domain"}: values.extend(rule["domain"])
            elif set(rule)=={"domain_suffix"}: values.extend("*."+x.lstrip(".") for x in rule["domain_suffix"])
        return values
    def routing(self): return {"vpn":self._domains(self._read("force-vpn.json")),"direct":self._domains(self._read("force-direct.json"))}
    def route_change(self,target,domain,remove=False):
        domain=RouteEntry(domain=domain).domain; data=self._read(f"force-{target}.json"); values=self._domains(data); other=self.routing()["direct" if target=="vpn" else "vpn"]
        if not remove and domain in other: raise ValueError("Domain conflicts with the other force rule-set")
        if remove: data["rules"]=[r for r in data["rules"] if not ((set(r)=={"domain"} and r["domain"]==[domain]) or (set(r)=={"domain_suffix"} and r["domain_suffix"]==["."+domain[2:]]))]
        elif domain not in values: data["rules"].append({"domain_suffix":["."+domain[2:]]} if domain.startswith("*.") else {"domain":[domain]})
        self._write(f"force-{target}.json",data); self._backup(f"{'Remove' if remove else 'Add'} {target} route {domain}")
    def backups(self): return [Backup(**x) for x in self._read("backups.json")]
    def logs(self): return (self.root/"logs.txt").read_text(encoding="utf-8").splitlines()[-100:]
    def client_config(self,name):
        device=next((x for x in self.devices() if x.name==name),None)
        if not device: raise ValueError("Device not found")
        from .client_config import build_client_config
        return build_client_config(device,self.status()["settings"])

class RpcAdapter:
    METHODS={"get_status","get_devices","add_device","enable_device","disable_device","delete_device","rotate_device_uuid","get_routing","add_force_vpn","remove_force_vpn","add_force_direct","remove_force_direct","get_ingress","test_direct","test_vpn","test_destination","get_recent_logs","list_backups","restore_backup"}
    def __init__(self,socket_path=None): self.socket_path=socket_path or os.getenv("VORTEX_NETCTL_SOCKET","/run/vortex-netctl/vortex-netctl.sock")
    def call(self,method,params=None):
        if method not in self.METHODS: raise ValueError("Forbidden RPC method")
        request_id=secrets.token_urlsafe(12).replace("-","a").replace("_","b")
        payload=json.dumps({"version":1,"request_id":request_id,"method":method,"params":params or {}},separators=(",",":"))+"\n"
        if len(payload)>8192: raise ValueError("Request exceeds size limit")
        try:
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as conn:
                conn.settimeout(8); conn.connect(self.socket_path); conn.sendall(payload.encode()); data=conn.makefile("rb").readline(16384)
        except OSError as exc: raise ConnectionError("Host agent unavailable") from exc
        reply=json.loads(data)
        if reply.get("version")!=1 or reply.get("request_id")!=request_id: raise ConnectionError("Invalid host agent response")
        if not reply.get("ok"): raise ValueError(reply.get("error",{}).get("message","Host agent error"))
        return reply["result"]

class ProductionAdapter:
    def __init__(self): self.rpc=RpcAdapter()
    def _call(self,method,params=None): return self.rpc.call(method,params)
    def status(self):
        try: return self._call("get_status")
        except (ConnectionError,ValueError): return {"agent_available":False,"core":[{"name":"Host agent","value":"Unavailable"}],"egress":[],"ingress":[],"settings":{}}
    def devices(self):
        data=self._call("get_devices")
        return [Device(name=x["name"],uuid="00000000-0000-0000-0000-000000000000",enabled=x.get("enabled",True)) for x in data["devices"]]
    def device_warnings(self): return self._call("get_devices").get("warnings",[])
    def client_config(self,name): return self._call("get_devices",{"device_name":name,"include_client_config":True})["client_config"]
    def add_device(self,name): return self._call("add_device",{"name":name})
    def change_device(self,name,action): return self._call({"enable":"enable_device","disable":"disable_device","delete":"delete_device","rotate":"rotate_device_uuid"}[action],{"name":name})
    def routing(self): return self._call("get_routing")
    def route_change(self,target,domain,remove=False): return self._call(("remove" if remove else "add")+f"_force_{target}",{"domain":domain})
    def backups(self): return self._call("list_backups")
    def logs(self): return self._call("get_recent_logs")