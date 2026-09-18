from __future__ import annotations

from copy import deepcopy
from uuid import uuid4
import re


CREATE_NAME_RE = re.compile(r"^[A-Z0-9_-]{2,48}$")


def validate_existing_name(name: str) -> str:
    if not isinstance(name, str) or not name or len(name) > 128:
        raise ValueError("Existing device name must be non-empty and at most 128 characters")
    if any(ord(char) < 32 or ord(char) == 127 for char in name) or "/" in name or "\\" in name:
        raise ValueError("Existing device name contains unsupported control or path characters")
    return name


def validate_create_name(name: str) -> str:
    if not isinstance(name, str) or not CREATE_NAME_RE.fullmatch(name):
        raise ValueError("Device name must match ^[A-Z0-9_-]{2,48}$")
    return name


def inbound(config: dict, tag: str) -> dict:
    found = [item for item in config.get("inbounds", []) if item.get("tag") == tag]
    if len(found) != 1 or not isinstance(found[0].get("users"), list):
        raise ValueError(f"Required VMess inbound {tag} is missing or invalid")
    return found[0]


def _users(config: dict) -> tuple[list[dict], list[dict]]:
    return inbound(config, "remote-vmess")["users"], inbound(config, "lan-vmess")["users"]


def analyze_devices(config: dict) -> dict:
    remote, lan = _users(config)

    def index(users):
        output, duplicates, invalid = {}, [], []
        for user in users:
            if not isinstance(user, dict):
                invalid.append("<non-object>")
                continue
            name, uuid = user.get("name"), user.get("uuid")
            try:
                validate_existing_name(name)
            except ValueError:
                invalid.append(str(name))
                continue
            if not isinstance(uuid, str):
                invalid.append(name)
                continue
            if name in output:
                duplicates.append(name)
            else:
                output[name] = uuid
        return output, duplicates, invalid

    rem, remdup, reminvalid = index(remote)
    loc, locdup, locinvalid = index(lan)
    shared, warnings = [], []
    for name in sorted(set(rem) | set(loc)):
        if name not in rem:
            warnings.append({"type": "orphan_lan", "name": name})
        elif name not in loc:
            warnings.append({"type": "orphan_remote", "name": name})
        elif rem[name] != loc[name]:
            warnings.append({"type": "uuid_mismatch", "name": name})
        else:
            shared.append({"name": name, "enabled": True})
    warnings += [{"type": "duplicate_remote", "name": name} for name in remdup]
    warnings += [{"type": "duplicate_lan", "name": name} for name in locdup]
    warnings += [{"type": "invalid_remote_name", "name": name} for name in reminvalid]
    warnings += [{"type": "invalid_lan_name", "name": name} for name in locinvalid]
    return {"devices": shared, "warnings": warnings}


def assert_device_diff_allowed(before: dict, after: dict) -> None:
    left, right = deepcopy(before), deepcopy(after)
    for value in (left, right):
        for item in value.get("inbounds", []):
            if item.get("tag") in {"remote-vmess", "lan-vmess"}:
                item.pop("users", None)
    if left != right:
        raise ValueError("Mutation would alter fields outside permitted inbound users lists")


def mutate_device(config: dict, operation: str, name: str) -> dict:
    if operation == "add":
        validate_create_name(name)
    else:
        validate_existing_name(name)
    result = deepcopy(config)
    remote, lan = _users(result)

    def matching(users):
        return [user for user in users if isinstance(user, dict) and user.get("name") == name]

    r, l = matching(remote), matching(lan)
    if operation == "add":
        if r or l:
            raise ValueError("Device name already exists in an inbound")
        new = {"name": name, "uuid": str(uuid4())}
        remote.append(deepcopy(new))
        lan.append(deepcopy(new))
        return result
    if len(r) != 1 or len(l) != 1:
        raise ValueError("Device is inconsistent across VMess inbounds; repair manually")
    if r[0].get("uuid") != l[0].get("uuid"):
        raise ValueError("Device UUID differs between VMess inbounds; repair manually")
    if operation == "rotate":
        value = str(uuid4())
        r[0]["uuid"] = value
        l[0]["uuid"] = value
    elif operation == "delete":
        remote[:] = [user for user in remote if not isinstance(user, dict) or user.get("name") != name]
        lan[:] = [user for user in lan if not isinstance(user, dict) or user.get("name") != name]
    elif operation in {"enable", "disable"}:
        raise ValueError("Enable/disable is unsupported for VMess users in production v1")
    else:
        raise ValueError("Unsupported device operation")
    return result