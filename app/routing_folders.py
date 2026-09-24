from __future__ import annotations
import json, os, tempfile, uuid, random
from pathlib import Path

FOLDER_COLORS = ('#f4a5b8', '#f5c581', '#e8dd8f', '#a9d9a1', '#8fd8c2', '#91caea', '#b7b7f3', '#d6a8e8')

class RoutingFolders:
    TARGETS = ("vpn", "direct")
    def __init__(self, path: Path): self.path = path
    def _blank(self): return {"version":1,"vpn":{"folders":[],"assignments":{}},"direct":{"folders":[],"assignments":{}}}
    def _folder_color(self, folder):
        color=folder.get("color"); return color if color in FOLDER_COLORS else FOLDER_COLORS[sum(map(ord,folder.get("id", "")))%len(FOLDER_COLORS)]
    def _migrate(self, data):
        vpn=data.setdefault("vpn", {"folders":[],"assignments":{}}); data.setdefault("direct", {"folders":[],"assignments":{}})
        legacy=data.pop("hyvpn", None)
        if not isinstance(legacy,dict): return data
        folders=vpn.setdefault("folders",[]); assignments=vpn.setdefault("assignments",{})
        names={str(f.get("name","")).casefold() for f in folders if isinstance(f,dict)}; ids={f.get("id") for f in folders if isinstance(f,dict)}; remap={}
        for old in legacy.get("folders",[]) if isinstance(legacy.get("folders"),list) else []:
            if not isinstance(old,dict) or not isinstance(old.get("id"),str): continue
            item=dict(old); base=str(item.get("name") or "HYVPN").strip()[:64] or "HYVPN"; name=base; number=2
            while name.casefold() in names: name=f"{base} (HYVPN)" if number==2 else f"{base} (HYVPN {number})"; number+=1
            item["name"]=name
            if item["id"] in ids: item["id"]="hyvpn-"+item["id"]
            while item["id"] in ids: item["id"]+="-x"
            names.add(name.casefold());ids.add(item["id"]);remap[old["id"]]=item["id"];folders.append(item)
        for domain,folder_id in (legacy.get("assignments",{}) or {}).items():
            if isinstance(domain,str) and domain not in assignments and folder_id in remap: assignments[domain]=remap[folder_id]
        return data
    def _read(self):
        try:
            data=json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("version")!=1: raise ValueError("unsupported version")
            data=self._migrate(data)
            for target in self.TARGETS:
                part=data.get(target)
                if not isinstance(part,dict) or not isinstance(part.get("folders",[]),list) or not isinstance(part.get("assignments",{}),dict): raise ValueError("invalid structure")
            return data
        except FileNotFoundError: return self._blank()
        except (OSError,ValueError,json.JSONDecodeError): return self._blank()
    def _write(self,data):
        self.path.parent.mkdir(parents=True,exist_ok=True);fd,tmp=tempfile.mkstemp(prefix="routing-folders-",dir=self.path.parent)
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as f: json.dump(data,f,ensure_ascii=False,separators=(",",":"));f.flush();os.fsync(f.fileno())
            os.replace(tmp,self.path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
    def state(self,routes):
        data=self._read();result={}
        for target in self.TARGETS:
            domains=set(routes.get(target,[]));part=data[target];ids={f.get("id") for f in part["folders"] if isinstance(f,dict) and isinstance(f.get("id"),str)}; assignments={d:f for d,f in part["assignments"].items() if d in domains and f in ids}
            folders=[{"id":"common","name":"Common","color":"#8fa1b6"}]+[{"id":f["id"],"name":f.get("name","") ,"color":self._folder_color(f)} for f in part["folders"] if f.get("id") in ids and f.get("name")]
            result[target]={"folders":folders,"assignments":assignments,"domains":sorted(domains)}
        return result
    def create(self,target,name):
        name=name.strip();data=self._read();part=data[target]
        if not name or len(name)>64 or any(f.get("name","").casefold()==name.casefold() for f in part["folders"]): raise ValueError("Folder name must be unique and non-empty")
        folder={"id":uuid.uuid4().hex,"name":name,"color":random.choice(FOLDER_COLORS)};part["folders"].append(folder);self._write(data);return folder
    def rename(self,target,folder_id,name):
        if folder_id=="common": raise ValueError("Common cannot be renamed")
        name=name.strip();data=self._read();part=data[target]
        if not name or any(f.get("id")!=folder_id and f.get("name","").casefold()==name.casefold() for f in part["folders"]): raise ValueError("Folder name must be unique and non-empty")
        folder=next((f for f in part["folders"] if f.get("id")==folder_id),None)
        if not folder: raise ValueError("Folder not found")
        folder["name"]=name;self._write(data);return folder
    def move(self,target,domain,folder_id):
        data=self._read();part=data[target];ids={f.get("id") for f in part["folders"]}
        if folder_id!="common" and folder_id not in ids: raise ValueError("Folder not found")
        if folder_id=="common":part["assignments"].pop(domain,None)
        else:part["assignments"][domain]=folder_id
        self._write(data)
    def delete(self,target,folder_id):
        data=self._read();part=data[target]
        if folder_id=="common": raise ValueError("Common cannot be deleted")
        if not any(f.get("id")==folder_id for f in part["folders"]): raise ValueError("Folder not found")
        domains=[d for d,f in part["assignments"].items() if f==folder_id];part["folders"]=[f for f in part["folders"] if f.get("id")!=folder_id]
        for d in domains:part["assignments"].pop(d,None)
        self._write(data);return domains