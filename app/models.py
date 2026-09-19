from __future__ import annotations

from datetime import datetime, timezone
import re
import uuid

from pydantic import BaseModel, field_validator


CREATE_DEVICE_NAME_RE = re.compile(r"^[A-Z0-9_-]{2,48}$")
DOMAIN_RE = re.compile(r"^(?:\*\.)?(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$", re.I)


def is_preferred_device_name(value: str) -> bool:
    return bool(CREATE_DEVICE_NAME_RE.fullmatch(value))


def validate_existing_device_name(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValueError("Existing device name must be non-empty and at most 128 characters")
    if any(ord(char) < 32 or ord(char) == 127 for char in value) or "/" in value or "\\" in value:
        raise ValueError("Existing device name contains unsupported control or path characters")
    return value


class CreateDeviceRequest(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if not is_preferred_device_name(value):
            raise ValueError("Use 2–48 uppercase A-Z, 0-9, _ or - characters")
        return value


class Device(BaseModel):
    name: str
    uuid: str
    enabled: bool = True
    subscription_status: str = "active"
    created_at: str | None = None
    notes: str = ""

    @field_validator("name")
    @classmethod
    def valid_existing_name(cls, value: str) -> str:
        return validate_existing_device_name(value)

    @field_validator("uuid")
    @classmethod
    def valid_uuid(cls, value: str) -> str:
        return str(uuid.UUID(value))

    @field_validator("subscription_status")
    @classmethod
    def valid_subscription_status(cls, value: str) -> str:
        if value not in {"active", "revoked"}:
            raise ValueError("Subscription status must be active or revoked")
        return value

    @property
    def legacy_name(self) -> bool:
        return not is_preferred_device_name(self.name)


class RouteEntry(BaseModel):
    domain: str

    @field_validator("domain")
    @classmethod
    def valid_domain(cls, value: str) -> str:
        value = value.lower().strip()
        if not DOMAIN_RE.fullmatch(value):
            raise ValueError("Enter a domain or *.wildcard domain only")
        return value


class Backup(BaseModel):
    id: str
    timestamp: str
    operation: str
    initiator: str = "panel"
    result: str


def now() -> str:
    return datetime.now(timezone.utc).isoformat()