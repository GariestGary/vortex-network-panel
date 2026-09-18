from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import logging
import os
import shutil
import stat
import tempfile
import time

try:
    import fcntl
except ImportError:
    fcntl = None

from .system import System


SUCCESS = "SUCCESS"
VALIDATION_FAILED = "VALIDATION_FAILED"
ROLLED_BACK = "APPLY_FAILED_ROLLED_BACK"
CRITICAL = "APPLY_FAILED_ROLLBACK_FAILED"
READINESS_TIMEOUT_SECONDS = 8.0
READINESS_POLL_SECONDS = 0.2

logger = logging.getLogger("vortex_netctl.transaction")


@dataclass
class TransactionResult:
    result: str
    message: str = ""
    backup_id: str | None = None


class TransactionManager:
    def __init__(self, system: System, backups: Path, lock_file: Path, health_check=None):
        self.system, self.backups, self.lock_file, self.health_check = system, backups, lock_file, health_check

    @contextmanager
    def _exclusive_lock(self):
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.lock_file, "a+") as lock:
            if fcntl:
                fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl:
                    fcntl.flock(lock, fcntl.LOCK_UN)

    def _write(self, path: Path, payload: bytes, source_stat: os.stat_result | None = None) -> None:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        if source_stat:
            os.chown(path, source_stat.st_uid, source_stat.st_gid)
            os.chmod(path, stat.S_IMODE(source_stat.st_mode))

    def _atomic(self, path: Path, payload: bytes, source_stat: os.stat_result) -> None:
        fd, temp = tempfile.mkstemp(prefix=".vortex-candidate-", dir=path.parent)
        os.close(fd)
        try:
            self._write(Path(temp), payload, source_stat)
            os.replace(temp, path)
            directory_fd = os.open(path.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def _backup(self, path: Path, operation: str) -> tuple[str, dict]:
        self.backups.mkdir(parents=True, exist_ok=True, mode=0o700)
        stamp = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_id = f"{stamp}-{hashlib.sha256(os.urandom(16)).hexdigest()[:8]}"
        target = self.backups / f"{backup_id}.json"
        shutil.copy2(path, target)
        data = path.read_bytes()
        metadata = {
            "id": backup_id,
            "timestamp": stamp,
            "operation": operation,
            "sha256": hashlib.sha256(data).hexdigest(),
            "mode": stat.S_IMODE(path.stat().st_mode),
            "uid": path.stat().st_uid,
            "gid": path.stat().st_gid,
        }
        logger.info("mutation backup created: %s", backup_id)
        return backup_id, metadata

    def _finalize_backup(self, metadata: dict, result: str) -> None:
        metadata = {**metadata, "result": result}
        backup_id = metadata["id"]
        (self.backups / f"{backup_id}.meta.json").write_text(json.dumps(metadata), encoding="utf-8")
        for stale in sorted(self.backups.glob("*.meta.json"))[:-10]:
            stale.with_suffix("").with_suffix(".json").unlink(missing_ok=True)
            stale.unlink(missing_ok=True)

    def _healthy(self) -> bool:
        if self.health_check:
            return self.health_check()
        return self.system.singbox_healthy() if hasattr(self.system, "singbox_healthy") else self.system.service_active("sing-box.service")

    def _wait_healthy(self) -> bool:
        deadline = time.monotonic() + READINESS_TIMEOUT_SECONDS
        while True:
            if self._healthy():
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(READINESS_POLL_SECONDS)

    @staticmethod
    def _candidate_persisted(path: Path, candidate: dict) -> bool:
        try:
            return json.loads(path.read_text(encoding="utf-8")) == candidate
        except (OSError, json.JSONDecodeError):
            return False

    def _result(self, result: str, message: str, backup_id: str | None, metadata: dict | None) -> TransactionResult:
        if metadata:
            self._finalize_backup(metadata, result)
        logger.info("mutation final result: %s", result)
        return TransactionResult(result, message, backup_id)

    def _rollback(self, path: Path, current: bytes, source_stat: os.stat_result, backup_id: str, metadata: dict, message: str) -> TransactionResult:
        logger.warning("mutation rollback start")
        try:
            self._atomic(path, current, source_stat)
            logger.info("mutation rollback restart")
            rollback_ok = self.system.restart_singbox().code == 0 and self._wait_healthy()
        except Exception:
            rollback_ok = False
        if rollback_ok:
            logger.info("mutation rollback success")
            return self._result(ROLLED_BACK, message, backup_id, metadata)
        logger.critical("mutation rollback failure")
        return self._result(CRITICAL, message, backup_id, metadata)

    def _apply_locked(self, path: Path, current: bytes, candidate: dict, operation: str, validate) -> TransactionResult:
        source_stat = path.stat()
        payload = (json.dumps(candidate, indent=2, ensure_ascii=False) + "\n").encode()
        fd, temp = tempfile.mkstemp(prefix=".vortex-validate-", dir=path.parent)
        os.close(fd)
        backup_id = None
        metadata = None
        try:
            logger.info("mutation start: %s", operation)
            self._write(Path(temp), payload, source_stat)
            checked = validate(Path(temp))
            if checked.code != 0:
                logger.warning("mutation validation failure: %s", operation)
                return TransactionResult(VALIDATION_FAILED, "Validation failed")
            logger.info("mutation validation success: %s", operation)
            backup_id, metadata = self._backup(path, operation)
            self._atomic(path, payload, source_stat)
            logger.info("mutation apply restart")
            if self.system.restart_singbox().code != 0:
                return self._rollback(path, current, source_stat, backup_id, metadata, "Service restart failed")
            if not self._wait_healthy():
                logger.warning("mutation health failure")
                return self._rollback(path, current, source_stat, backup_id, metadata, "Service readiness check failed")
            if not self._candidate_persisted(path, candidate):
                logger.error("mutation post-apply invariant failure")
                return self._rollback(path, current, source_stat, backup_id, metadata, "Post-apply invariant failed")
            logger.info("mutation health success")
            return self._result(SUCCESS, "", backup_id, metadata)
        except Exception as exc:
            logger.exception("mutation apply failure: %s", type(exc).__name__)
            if backup_id and metadata:
                return self._rollback(path, current, source_stat, backup_id, metadata, "Apply failed")
            return TransactionResult(VALIDATION_FAILED, "Validation failed")
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def apply_json(self, path: Path, candidate: dict, operation: str, validate) -> TransactionResult:
        with self._exclusive_lock():
            return self._apply_locked(path, path.read_bytes(), candidate, operation, validate)

    def apply_mutation(self, path: Path, operation: str, mutate, validate) -> TransactionResult:
        with self._exclusive_lock():
            current = path.read_bytes()
            candidate = mutate(json.loads(current))
            return self._apply_locked(path, current, candidate, operation, validate)
