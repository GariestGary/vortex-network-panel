from __future__ import annotations
from datetime import datetime, timezone
from pydantic import BaseModel, Field, field_validator
import re, uuid

NAME_RE = re.compile(r"^[A-Z0-9_-]{2,48}$")
DOMAIN_RE = re.compile(r"^(?:\*\.)?(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$", re.I)

class Device(BaseModel):
    name: str
    uuid: str
    enabled: bool = True
    created_at: str | None = None
    notes: str = ""
    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if not NAME_RE.fullmatch(value): raise ValueError("Use 2–48 uppercase A-Z, 0-9, _ or - characters")
        return value
    @field_validator("uuid")
    @classmethod
    def valid_uuid(cls, value: str) -> str:
        return str(uuid.UUID(value))

class RouteEntry(BaseModel):
    domain: str
    @field_validator("domain")
    @classmethod
    def valid_domain(cls, value: str) -> str:
        value = value.lower().strip()
        if not DOMAIN_RE.fullmatch(value): raise ValueError("Enter a domain or *.wildcard domain only")
        return value

class Backup(BaseModel):
    id: str
    timestamp: str
    operation: str
    initiator: str = "panel"
    result: str

def now() -> str: return datetime.now(timezone.utc).isoformat()

