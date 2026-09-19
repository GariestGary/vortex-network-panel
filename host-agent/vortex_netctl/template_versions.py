from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat


RETENTION = 20


class TemplateVersionError(ValueError):
    pass


class TemplateVersions:
    def __init__(self, path: Path):
        self.path = path

    @staticmethod
    def revision(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _version_path(self, version_id: str) -> Path:
        if not __import__("re").fullmatch(r"[0-9TZ-]+-[a-f0-9]{16}", version_id):
            raise TemplateVersionError("Invalid template version")
        return self.path / f"{version_id}.json"

    def preserve(self, content: str) -> dict:
        self.path.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path, 0o700)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        version_id = f"{stamp}-{secrets.token_hex(8)}"
        record = {"id": version_id, "timestamp": stamp, "sha256": self.revision(content), "template": content}
        target = self._version_path(version_id)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            data = (json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.chmod(target, 0o600)
        self._prune()
        return {key: record[key] for key in ("id", "timestamp", "sha256")}

    def _prune(self) -> None:
        for stale in sorted(self.path.glob("*.json"), reverse=True)[RETENTION:]:
            stale.unlink(missing_ok=True)

    def list(self) -> list[dict]:
        if not self.path.exists():
            return []
        records = []
        for path in sorted(self.path.glob("*.json"), reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("id") != path.stem or not isinstance(data.get("timestamp"), str) or not isinstance(data.get("sha256"), str):
                    continue
                records.append({key: data[key] for key in ("id", "timestamp", "sha256")})
            except (OSError, json.JSONDecodeError, KeyError):
                continue
        return records

    def load(self, version_id: str) -> str:
        try:
            data = json.loads(self._version_path(version_id).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TemplateVersionError("Template version is unavailable") from exc
        content = data.get("template")
        if data.get("id") != version_id or not isinstance(content, str) or data.get("sha256") != self.revision(content):
            raise TemplateVersionError("Template version is invalid")
        return content