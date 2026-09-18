from __future__ import annotations
from copy import deepcopy
from uuid import uuid4
import re

NAME_RE = re.compile(r"^[A-Z0-9_-]{1,32}$")

def inbound(config: dict, tag: str) -> dict:
    found = [item for item in config.get("inbounds", []) if item.get("tag") == tag]
    if len(found) != 1 or not isinstance(found[0].get("users"), list): raise ValueError(f"Required VMess inbound {tag} is missing or invalid")
    return found[0]

def _users(config: dict) -> tuple[list[dict], list[dict]]:
    return inbound(config, "remote-vmess")["users"], inbound(config, "lan-vmess")["users"]

def analyze_devices(config: dict) -> dict:
    remote, lan = _users(config)
    def index(users):
        output={}; duplicates=[]
        for user in users:
            name=user.get("name"); uuid=user.get("uuid")
            if not isinstance(name,str) or not isinstance(uuid,str): continue
            if name in output: duplicates.append(name)
            else: output[name]=uuid
        return output,duplicates
    rem, remdup = index(remote); loc, locdup = index(lan)
    shared=[]; warnings=[]
    for name in sorted(set(rem)|set(loc)):
        if name not in rem: warnings.append({"type":"orphan_lan","name":name})
        elif name not in loc: warnings.append({"type":"orphan_remote","name":name})
        elif rem[name] != loc[name]: warnings.append({"type":"uuid_mismatch","name":name})
        else: shared.append({"name":name,"enabled":True})
    warnings += [{"type":"duplicate_remote","name":x} for x in remdup] + [{"type":"duplicate_lan","name":x} for x in locdup]
    return {"devices":shared,"warnings":warnings}

def assert_device_diff_allowed(before: dict, after: dict) -> None:
    left,right=deepcopy(before),deepcopy(after)
    for value in (left,right):
        for item in value.get("inbounds",[]):
            if item.get("tag") in {"remote-vmess","lan-vmess"}: item.pop("users",None)
    if left != right: raise ValueError("Mutation would alter fields outside permitted inbound users lists")

def mutate_device(config: dict, operation: str, name: str) -> dict:
    if not NAME_RE.fullmatch(name): raise ValueError("Device name must match ^[A-Z0-9_-]{1,32}$")
    result=deepcopy(config); remote,lan=_users(result)
    def matching(users): return [u for u in users if u.get("name")==name]
    r,l=matching(remote),matching(lan)
    if operation == "add":
        if r or l: raise ValueError("Device name already exists in an inbound")
        new={"name":name,"uuid":str(uuid4())}; remote.append(deepcopy(new)); lan.append(deepcopy(new)); return result
    if len(r)!=1 or len(l)!=1: raise ValueError("Device is inconsistent across VMess inbounds; repair manually")
    if r[0].get("uuid") != l[0].get("uuid"): raise ValueError("Device UUID differs between VMess inbounds; repair manually")
    if operation == "rotate":
        value=str(uuid4()); r[0]["uuid"]=value; l[0]["uuid"]=value
    elif operation == "delete":
        remote[:]=[u for u in remote if u.get("name")!=name]; lan[:]=[u for u in lan if u.get("name")!=name]
    elif operation in {"enable","disable"}: raise ValueError("Enable/disable is unsupported for VMess users in production v1")
    else: raise ValueError("Unsupported device operation")
    return result
