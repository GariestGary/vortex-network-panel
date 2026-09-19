from __future__ import annotations

import hmac
import json
import os
import secrets
import tempfile
from pathlib import Path


class SubscriptionStore:
    def __init__(self, path: Path):
        self.path = path

    @staticmethod
    def _new_token(records: dict) -> str:
        existing = {record.get("token") for record in records.values() if isinstance(record, dict)}
        while True:
            token = secrets.token_urlsafe(32)
            if token not in existing:
                return token

    def _load(self) -> dict:
        if not self.path.exists():
            return {"version": 1, "devices": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Subscription state is unavailable") from exc
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("devices"), dict):
            raise ValueError("Subscription state is invalid")
        for name, record in data["devices"].items():
            if not isinstance(name, str) or not isinstance(record, dict) or type(record.get("revoked")) is not bool:
                raise ValueError("Subscription state is invalid")
            token = record.get("token")
            if not record["revoked"] and (not isinstance(token, str) or not token):
                raise ValueError("Subscription state is invalid")
        return data

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(prefix=".vortex-subscriptions-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
            directory_fd = os.open(self.path.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def synchronize(self, device_names: set[str]) -> dict:
        data = self._load()
        records = data["devices"]
        changed = False
        for name in device_names:
            if name not in records:
                records[name] = {"token": self._new_token(records), "revoked": False}
                changed = True
        for name in set(records) - device_names:
            del records[name]
            changed = True
        if changed:
            self._save(data)
        return data

    def token_for(self, name: str, device_names: set[str]) -> str:
        record = self.synchronize(device_names)["devices"].get(name)
        if not record or record["revoked"]:
            raise ValueError("Subscription token not found")
        return record["token"]

    def rotate(self, name: str, device_names: set[str]) -> str:
        data = self.synchronize(device_names)
        record = data["devices"].get(name)
        if not record:
            raise ValueError("Device not found")
        record.update(token=self._new_token(data["devices"]), revoked=False)
        self._save(data)
        return record["token"]

    def revoke(self, name: str, device_names: set[str]) -> None:
        data = self.synchronize(device_names)
        record = data["devices"].get(name)
        if not record:
            raise ValueError("Device not found")
        record.update(token=None, revoked=True)
        self._save(data)

    def device_for_token(self, token: str, device_names: set[str]) -> str:
        records = self.synchronize(device_names)["devices"]
        found = None
        for name, record in records.items():
            value = record.get("token")
            if not record["revoked"] and isinstance(value, str) and hmac.compare_digest(token, value):
                found = name
        if found is None:
            raise ValueError("Subscription not found")
        return found
