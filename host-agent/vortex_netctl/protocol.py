from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .singbox import validate_create_name, validate_existing_name


MAX_REQUEST_BYTES = 8192
METHODS = {"get_status", "get_devices", "add_device", "enable_device", "disable_device", "delete_device", "rotate_device_uuid", "get_routing", "add_force_vpn", "remove_force_vpn", "add_force_direct", "remove_force_direct", "get_ingress", "test_direct", "test_vpn", "test_destination", "get_recent_logs", "list_backups", "restore_backup"}


class Params(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateDeviceParams(Params):
    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return validate_create_name(value)


class ExistingDeviceParams(Params):
    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return validate_existing_name(value)


class DomainParams(Params):
    domain: str = Field(max_length=253)


class DestinationParams(Params):
    destination: str = Field(max_length=253)


class BackupParams(Params):
    backup_id: str = Field(max_length=64)


class DeviceConfigParams(Params):
    device_name: str
    include_client_config: Literal[True]

    @field_validator("device_name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return validate_existing_name(value)


class RpcRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")
    method: Literal["get_status", "get_devices", "add_device", "enable_device", "disable_device", "delete_device", "rotate_device_uuid", "get_routing", "add_force_vpn", "remove_force_vpn", "add_force_direct", "remove_force_direct", "get_ingress", "test_direct", "test_vpn", "test_destination", "get_recent_logs", "list_backups", "restore_backup"]
    params: dict


def parse_request(line: bytes) -> tuple[RpcRequest, Params]:
    if len(line) > MAX_REQUEST_BYTES:
        raise ValueError("Request exceeds size limit")
    try:
        request = RpcRequest.model_validate_json(line)
    except ValidationError as exc:
        raise ValueError("Malformed RPC request") from exc
    cls: type[Params] = Params
    if request.method == "add_device":
        cls = CreateDeviceParams
    elif request.method in {"enable_device", "disable_device", "delete_device", "rotate_device_uuid"}:
        cls = ExistingDeviceParams
    elif request.method in {"add_force_vpn", "remove_force_vpn", "add_force_direct", "remove_force_direct"}:
        cls = DomainParams
    elif request.method == "test_destination":
        cls = DestinationParams
    elif request.method == "restore_backup":
        cls = BackupParams
    elif request.method == "get_devices" and request.params:
        cls = DeviceConfigParams
    try:
        return request, cls.model_validate(request.params)
    except ValidationError as exc:
        raise ValueError("Invalid RPC parameters") from exc


def response(request_id: str, result=None, error: tuple[str, str] | None = None) -> bytes:
    payload = {"version": 1, "request_id": request_id, "ok": error is None}
    if error:
        payload["error"] = {"code": error[0], "message": error[1]}
    else:
        payload["result"] = result
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode()