from __future__ import annotations
import json, os, tempfile, uuid, random
from pathlib import Path

FOLDER_COLORS = ('#f4a5b8', '#f5c581', '#e8dd8f', '#a9d9a1', '#8fd8c2', '#91caea', '#b7b7f3', '#d6a8e8')

class RoutingFolders:
    TARGETS = ("vpn", "hyvpn", "direct")
    def __init__(self, path: Path): self.path = path
    def _blank(self): return {"version":1, **{target:{"folders":[],"assignments":{}} for target in self.TARGETS}}
    def _folder_color(self, folder):
        color = folder.get("color")
        return color if color in FOLDER_COLORS else FOLDER_COLORS[sum(map(ord, folder.get("id", ""))) % len(FOLDER_COLORS)]
    def _read(self):
        try:
            data=json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("version")!=1: raise ValueError("unsupported version")
            # Version 1 remains backward-compatible; HYVPN is added lazily.
            for target in self.TARGETS:
                if target not in data: data[target] = {"folders": [], "assignments": {}}
                if not isinstance(data.get(target),dict) or not isinstance(data[target].get("folders",[]),list) or not isinstance(data[target].get("assignments",{}),dict): raise ValueError("invalid structure")
            return data
        except FileNotFoundError: return self._blank()
        except (OSError,ValueError,json.JSONDecodeError): return self._blank()
    def _write(self,data):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix="routing-folders-",dir=self.path.parent)
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as f: json.dump(data,f,ensure_ascii=False,separators=(",",":"));f.flush();os.fsync(f.fileno())
            os.replace(tmp,self.path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
    def state(self,routes):
        data=self._read()
        result={}
        for target in self.TARGETS:
            domains=set(routes.get(target,[])); part=data[target]; ids={f.get("id") for f in part["folders"] if isinstance(f,dict) and isinstance(f.get("id"),str)}
            assignments={d:f for d,f in part["assignments"].items() if d in domains and f in ids}
            folders=[{"id":"common","name":"Common","color":"#8fa1b6"}]+[{"id":f["id"],"name":f.get("name","") ,"color":self._folder_color(f)} for f in part["folders"] if f.get("id") in ids and f.get("name")]
            result[target]={"folders":folders,"assignments":assignments,"domains":sorted(domains)}
        # Bootstrap is deliberately read-only: missing or unwritable metadata must not hide real routing rules.
        return result
    def create(self,target,name):
        name=name.strip(); data=self._read(); part=data[target]
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
        data=self._read();part=data[target]; ids={f.get("id") for f in part["folders"]}
        if folder_id!="common" and folder_id not in ids: raise ValueError("Folder not found")
        if folder_id=="common":part["assignments"].pop(domain,None)
        else:part["assignments"][domain]=folder_id
        self._write(data)
    def delete(self,target,folder_id):
        data=self._read();part=data[target]
        if folder_id=="common": raise ValueError("Common cannot be deleted")
        if not any(f.get("id")==folder_id for f in part["folders"]): raise ValueError("Folder not found")
        domains=[d for d,f in part["assignments"].items() if f==folder_id]
        part["folders"]=[f for f in part["folders"] if f.get("id")!=folder_id]
        for d in domains:part["assignments"].pop(d,None)
        self._write(data);return domains
