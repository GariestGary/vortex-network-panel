from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from .singbox import validate_create_name, validate_existing_name

MAX_REQUEST_BYTES = 262144
METHODS = {"get_status", "get_devices", "add_device", "enable_device", "disable_device", "delete_device", "rotate_device_uuid", "get_subscription_token", "rotate_subscription_token", "revoke_subscription_token", "get_client_template", "validate_client_template", "save_client_template", "list_client_template_versions", "restore_client_template_version", "get_routing", "add_force_vpn", "remove_force_vpn", "add_force_direct", "remove_force_direct", "get_vpn_provider", "set_vpn_provider", "get_hyvpn", "set_hyvpn_profile", "get_ingress", "test_direct", "test_vpn", "test_destination", "get_recent_logs", "list_backups", "restore_backup"}

class Params(BaseModel): model_config = ConfigDict(extra="forbid")
class CreateDeviceParams(Params):
    name: str
    @field_validator("name")
    @classmethod
    def validate_name(cls, value): return validate_create_name(value)
class ExistingDeviceParams(Params):
    name: str
    @field_validator("name")
    @classmethod
    def validate_name(cls, value): return validate_existing_name(value)
class DomainParams(Params): domain: str = Field(max_length=253)
class DestinationParams(Params): destination: str = Field(max_length=253)
class BackupParams(Params): backup_id: str = Field(max_length=64)
class HyvpnProfileParams(Params): profile_id: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9:_-]+$")
class VpnProviderParams(Params): provider: Literal["amnezia", "hyvpn"]
class ClientTemplateParams(Params): template: str = Field(min_length=1, max_length=131072)
class SaveClientTemplateParams(ClientTemplateParams): expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
class RestoreClientTemplateParams(Params):
    version_id: str = Field(pattern=r"^[0-9TZ-]+-[a-f0-9]{16}$")
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
class DeviceConfigParams(Params):
    device_name: str
    include_client_config: Literal[True]
    @field_validator("device_name")
    @classmethod
    def validate_name(cls, value): return validate_existing_name(value)

class RpcRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")
    method: Literal["get_status", "get_devices", "add_device", "enable_device", "disable_device", "delete_device", "rotate_device_uuid", "get_subscription_token", "rotate_subscription_token", "revoke_subscription_token", "get_client_template", "validate_client_template", "save_client_template", "list_client_template_versions", "restore_client_template_version", "get_routing", "add_force_vpn", "remove_force_vpn", "add_force_direct", "remove_force_direct", "get_vpn_provider", "set_vpn_provider", "get_hyvpn", "set_hyvpn_profile", "get_ingress", "test_direct", "test_vpn", "test_destination", "get_recent_logs", "list_backups", "restore_backup"]
    params: dict
class SubscriptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")
    token: str = Field(min_length=1, max_length=128)

def parse_request(line: bytes) -> tuple[RpcRequest, Params]:
    if len(line) > MAX_REQUEST_BYTES: raise ValueError("Request exceeds size limit")
    try: request = RpcRequest.model_validate_json(line)
    except ValidationError as exc: raise ValueError("Malformed RPC request") from exc
    mapping = {"add_device": CreateDeviceParams, "enable_device": ExistingDeviceParams, "disable_device": ExistingDeviceParams, "delete_device": ExistingDeviceParams, "rotate_device_uuid": ExistingDeviceParams, "get_subscription_token": ExistingDeviceParams, "rotate_subscription_token": ExistingDeviceParams, "revoke_subscription_token": ExistingDeviceParams, "add_force_vpn": DomainParams, "remove_force_vpn": DomainParams, "add_force_direct": DomainParams, "remove_force_direct": DomainParams, "set_vpn_provider": VpnProviderParams, "set_hyvpn_profile": HyvpnProfileParams, "test_destination": DestinationParams, "restore_backup": BackupParams, "validate_client_template": ClientTemplateParams, "save_client_template": SaveClientTemplateParams, "restore_client_template_version": RestoreClientTemplateParams}
    cls = DeviceConfigParams if request.method == "get_devices" and request.params else mapping.get(request.method, Params)
    try: return request, cls.model_validate(request.params)
    except ValidationError as exc: raise ValueError("Invalid RPC parameters") from exc

def parse_subscription_request(line: bytes) -> SubscriptionRequest:
    if len(line) > MAX_REQUEST_BYTES: raise ValueError("Request exceeds size limit")
    try: return SubscriptionRequest.model_validate_json(line)
    except ValidationError as exc: raise ValueError("Malformed subscription request") from exc

def response(request_id: str, result=None, error: tuple[str, str] | None = None) -> bytes:
    payload = {"version": 1, "request_id": request_id, "ok": error is None}
    if error: payload["error"] = {"code": error[0], "message": error[1]}
    else: payload["result"] = result
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode()