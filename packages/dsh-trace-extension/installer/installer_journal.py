"""Transactional file operations, per-profile locking, and crash recovery journal."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

OWNER = "dsh-trace-extension"
STATE_VERSION = 1
MARKETPLACE = "rollout-local"
PLUGIN = "codex-dsh-trace@rollout-local"
ENV_KEY = "CODEX_ROLLOUT_TRACE_ROOT"
LABEL = "io.dsh-trace-extension.codex-recording"
UNSET = object()


class SetupError(Exception):
    """A preflight, configuration, or command error with an actionable message."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def absolute(value: os.PathLike[str] | str, home: Path | None = None) -> Path:
    text = os.fspath(value)
    if home is not None and (text == "~" or text.startswith("~/")):
        text = str(home) + text[1:]
    return Path(os.path.abspath(os.path.expanduser(text)))


def safe_path(path: Path | str) -> Path:
    """Refuse symlinks, including symlinked ancestors, before managed writes."""
    resolved = Path(path)
    for candidate in (resolved, *resolved.parents):
        if candidate.is_symlink():
            raise SetupError(f"Refusing symlinked setup path: {candidate}")
    return resolved


class OperationJournalMixin:
    """Managed atomic writes, backups, profile lock, rollback, and WAL recovery."""

    home: Path
    codex_home: Path
    state_path: Path
    pending_path: Path
    trace_root: Path
    launch_path: Path
    args: Any
    bundle: Any
    state: dict[str, Any] | None
    install_source: str | None
    launchctl: str | None
    journal: list[tuple[Path, bytes | None, str | None]]
    created_dirs: list[Path]
    warnings: list[str]
    pending: dict[str, Any] | None
    pending_raw: bytes | None
    recording_intents: bool
    operation_lock: int | None

    def bundled(self, method: str, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def retain_bundle_source(self) -> None:
        raise NotImplementedError

    def environment(self) -> str | None:
        raise NotImplementedError

    def inspect_marketplace(self) -> bool:
        raise NotImplementedError

    def installed_plugin(self, marketplace_exists: bool = True) -> dict[str, Any] | None:
        raise NotImplementedError

    def confirm(self, plan: dict[str, Any]) -> None:
        raise NotImplementedError

    def command(self, command: list[Any], required: bool = True) -> Any:
        raise NotImplementedError

    def bytes_at(self, path: Path) -> bytes | None:
        safe_path(path)
        if not path.exists():
            return None
        if not path.is_file():
            raise SetupError(f"Preserving non-file configuration path: {path}")
        if path.stat().st_size > 128 * 1024 * 1024:
            raise SetupError(f"Preserving oversized configuration file: {path}")
        return path.read_bytes()

    def expect_bytes(self, path: Path, expected: bytes | None) -> None:
        if self.bytes_at(path) != expected:
            raise SetupError(
                f"Configuration changed since inspection; preserving {path}. Rerun setup."
            )

    def managed_operation_path(self, value: str) -> Path:
        path = absolute(value)
        safe_path(path)
        if path in (self.state_path, self.launch_path):
            return path
        roots = (
            self.codex_home / OWNER / "marketplace",
            self.codex_home / "plugins/cache" / MARKETPLACE / "codex-dsh-trace",
        )
        if any(root in path.parents for root in roots):
            return path
        raise SetupError("Recovery record names an unrelated path; preserve it for review.")

    def operation_lock_path(self) -> Path:
        return (
            self.home / "Library/Caches" / OWNER / (digest(str(self.codex_home).encode()) + ".lock")
        )

    def acquire_operation_lock(self) -> None:
        if self.operation_lock is not None:
            return
        import fcntl

        path = self.operation_lock_path()
        safe_path(path)
        self.ensure_directory(path.parent)
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(descriptor)
            raise SetupError(
                "Another setup/uninstall is running in this Codex profile. Wait for it to finish, then retry."
            ) from exc
        self.operation_lock = descriptor

    def release_operation_lock(self) -> None:
        if self.operation_lock is not None:
            os.close(self.operation_lock)
            self.operation_lock = None

    def operation_busy(self) -> bool:
        import fcntl

        path = self.operation_lock_path()
        safe_path(path)
        if not path.exists() or self.operation_lock is not None:
            return False
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return False
            except BlockingIOError:
                return True
        finally:
            os.close(descriptor)

    def operation_directory(self, value: str, trace_root: str) -> Path:
        path = absolute(value)
        safe_path(path)
        roots = (
            self.codex_home / OWNER / "marketplace",
            self.codex_home / "plugins/cache" / MARKETPLACE / "codex-dsh-trace",
        )
        if path in (
            absolute(trace_root),
            self.launch_path.parent,
            self.launch_path.parent.parent,
        ) or any(path == root or root in path.parents for root in roots):
            return path
        raise SetupError("Recovery record names an unrelated directory; preserve it for review.")

    @staticmethod
    def decode_before(value: Any) -> bytes | None:
        if value is None:
            return None
        if not isinstance(value, str) or len(value) > 4 * 1024 * 1024:
            raise SetupError("Invalid recovery snapshot; preserve operation.json for review.")
        try:
            return base64.b64decode(value, validate=True)
        except ValueError as exc:
            raise SetupError("Invalid recovery snapshot encoding.") from exc

    @staticmethod
    def matches_recorded_write(current: bytes | None, checksum: str | None) -> bool:
        return (
            current is None
            if checksum is None
            else current is not None and digest(current) == checksum
        )

    def load_pending(self) -> dict[str, Any] | None:
        raw = self.bytes_at(self.pending_path)
        if raw is None:
            self.pending = self.pending_raw = None
            return None
        try:
            if len(raw) > 16 * 1024 * 1024:
                raise ValueError("oversized")
            value = json.loads(raw)
            if (
                not isinstance(value, dict)
                or set(value)
                != {
                    "format",
                    "owner",
                    "source",
                    "candidate",
                    "traceRoot",
                    "origin",
                    "writes",
                    "directories",
                    "environmentIntent",
                    "pluginIntent",
                    "phase",
                    "persist",
                }
                or value["format"] != 1
                or value["owner"] != OWNER
                or value["source"] != self.install_source
                or value["phase"] not in ("applying", "recovered")
                or not isinstance(value["persist"], bool)
                or not isinstance(value["candidate"], dict)
                or set(value["candidate"]) != {"version", "packageDigest"}
                or not isinstance(value["traceRoot"], str)
                or not Path(value["traceRoot"]).is_absolute()
                or not isinstance(value["origin"], dict)
                or set(value["origin"])
                != {
                    "state",
                    "receipt",
                    "environment",
                    "plugin",
                    "pluginOwned",
                    "environmentOwned",
                    "previousEnvironment",
                }
                or not isinstance(value["origin"]["pluginOwned"], bool)
                or not isinstance(value["origin"]["environmentOwned"], bool)
                or not isinstance(value["writes"], list)
                or len(value["writes"]) > 4096
                or not isinstance(value["directories"], list)
                or len(value["directories"]) > 4000
                or not isinstance(value["environmentIntent"], bool)
                or not isinstance(value["pluginIntent"], bool)
            ):
                raise ValueError("identity")
            candidate = value["candidate"]
            if (
                not isinstance(candidate["version"], str)
                or len(candidate["version"]) > 80
                or not all(c.isascii() and (c.isalnum() or c in ".-") for c in candidate["version"])
                or not isinstance(candidate["packageDigest"], str)
                or len(candidate["packageDigest"]) != 64
                or any(c not in "0123456789abcdef" for c in candidate["packageDigest"])
            ):
                raise ValueError("candidate")
            if value["origin"]["plugin"] is not None and (
                not isinstance(value["origin"]["plugin"], dict)
                or value["origin"]["plugin"].get("pluginId") != PLUGIN
            ):
                raise ValueError("plugin")
            for key in ("environment", "previousEnvironment"):
                if value["origin"][key] is not None and not isinstance(value["origin"][key], str):
                    raise ValueError("environment")
            for key in ("state", "receipt"):
                self.decode_before(value["origin"][key])
            for directory in value["directories"]:
                if str(self.operation_directory(directory, value["traceRoot"])) != directory:
                    raise ValueError("directory")
            seen = set()
            for entry in value["writes"]:
                if not isinstance(entry, dict) or set(entry) != {"path", "before", "after"}:
                    raise ValueError("write")
                path = self.managed_operation_path(entry["path"])
                if str(path) != entry["path"] or path in seen:
                    raise ValueError("path")
                seen.add(path)
                self.decode_before(entry["before"])
                if entry["after"] is not None and (
                    not isinstance(entry["after"], str)
                    or len(entry["after"]) != 64
                    or any(c not in "0123456789abcdef" for c in entry["after"])
                ):
                    raise ValueError("checksum")
            self.pending, self.pending_raw = value, raw
            return value
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise SetupError(
                f"Unrecognized recovery record at {self.pending_path}; preserve it and review the file before retrying. No automatic adoption is allowed."
            ) from exc

    def save_pending(self) -> None:
        data = (json.dumps(self.pending, sort_keys=True, indent=2) + "\n").encode()
        self.atomic_bytes(self.pending_path, data, expected=self.pending_raw)
        self.pending_raw = data

    def begin_operation(self, plan: dict[str, Any]) -> None:
        if self.pending is None:

            def encode(value: bytes | None) -> str | None:
                return base64.b64encode(value).decode() if value is not None else None

            owned = bool((self.state and self.state["pluginOwned"]) or not plan["_plugin"])
            self.pending = {
                "format": 1,
                "owner": OWNER,
                "source": self.install_source,
                "candidate": {
                    "version": self.bundle.version,
                    "packageDigest": self.bundle.package_digest,
                },
                "traceRoot": str(self.trace_root),
                "origin": {
                    "state": encode(plan["_state_bytes"]),
                    "receipt": encode(self.bytes_at(self.bundle.receipt_path)),
                    "plugin": plan["_plugin"],
                    "environment": plan["_environment"],
                    "pluginOwned": owned,
                    "environmentOwned": bool(
                        plan["_environment_owned"] or plan["_environment"] != str(self.trace_root)
                    ),
                    "previousEnvironment": self.state.get("previousEnvironment")
                    if plan["_environment_owned"] and self.state
                    else plan["_environment"],
                },
                "writes": [],
                "directories": [],
                "environmentIntent": False,
                "pluginIntent": False,
                "phase": "applying",
                "persist": not self.args.no_persist,
            }
        self.pending["phase"] = "applying"
        self.save_pending()
        self.recording_intents = True

    def record_write(self, path: Path, before: bytes | None, after: bytes | None) -> None:
        if not self.recording_intents or self.pending is None:
            return
        self.managed_operation_path(str(path))
        entry = {
            "path": str(path),
            "before": base64.b64encode(before).decode() if before is not None else None,
            "after": digest(after) if after is not None else None,
        }
        existing = next(
            (item for item in self.pending["writes"] if item["path"] == str(path)), None
        )
        if existing is not None:
            if existing == entry:
                return
            raise SetupError(
                "A recovery path was staged twice; preserve operation.json and retry setup."
            )
        if len(self.pending["writes"]) >= 4096:
            raise SetupError(
                "The operation reached its write budget. Keep operation.json for recovery."
            )
        self.pending["writes"].append(entry)
        self.save_pending()

    def recover_operation(self) -> dict[str, Any] | None:
        operation = self.pending
        assert operation is not None
        if self.operation_busy():
            raise SetupError(
                "The recorded installation is still running. Wait for it to finish before retrying recovery."
            )
        if operation["candidate"] != {
            "version": self.bundle.version,
            "packageDigest": self.bundle.package_digest,
        }:
            raise SetupError(
                f"Finish the interrupted version first: npx dsh-trace-extension@{operation['candidate']['version']} setup. Keep {self.pending_path} for recovery."
            )
        self.trace_root = absolute(operation["traceRoot"])
        if self.args.trace_root and absolute(self.args.trace_root, self.home) != self.trace_root:
            raise SetupError(
                "Finish the recorded trace-root first. Omit --trace-root when retrying this operation; choose a new location after recovery completes."
            )
        self.args.no_persist = not operation["persist"]
        report = {
            "commands": [],
            "changes": [{"action": "recover-interrupted-setup", "path": str(self.pending_path)}],
            "notes": [
                "Restore only recorded, unchanged writes, preserve Codex registrations, then retry this verified package. Recordings are retained."
            ],
        }
        for entry in operation["writes"]:
            path = self.managed_operation_path(entry["path"])
            current, before = self.bytes_at(path), self.decode_before(entry["before"])
            if current != before and not self.matches_recorded_write(current, entry["after"]):
                raise SetupError(
                    f"Recovery found a user edit at {path}; preserve it and operation.json, review that path, then retry. Nothing was overwritten."
                )
        written = {entry["path"] for entry in operation["writes"]}
        if str(self.state_path) not in written and self.bytes_at(
            self.state_path
        ) != self.decode_before(operation["origin"]["state"]):
            raise SetupError(
                "Setup state changed after interruption; preserve it and operation.json for review."
            )
        receipt_before = self.decode_before(operation["origin"]["receipt"])
        if receipt_before is not None:
            try:
                receipt = json.loads(receipt_before)
                manifest, templates = self.bundled("_receipt_payload", receipt)
                expected_files = self.bundle._receipt_files(
                    manifest, templates, receipt["activeBundle"], receipt["pythonExecutable"]
                )
                if expected_files != receipt["files"]:
                    raise ValueError("receipt")
                for name, checksum in expected_files.items():
                    path = self.bundle.source_path / name
                    if str(path) not in written:
                        current = self.bytes_at(path)
                        if current is None or digest(current) != checksum:
                            raise SetupError(
                                f"Previous source changed after interruption: {path}. Preserve it before recovery."
                            )
            except (ValueError, KeyError, TypeError) as exc:
                raise SetupError(
                    "Recovery contains an invalid prior receipt; preserve it for review."
                ) from exc
        current_env = self.environment()
        if operation["environmentIntent"] and current_env not in (
            operation["origin"]["environment"],
            str(self.trace_root),
        ):
            raise SetupError(
                "Recording environment changed after interruption; preserve it and review operation.json before retrying."
            )
        if not operation["environmentIntent"] and current_env != operation["origin"]["environment"]:
            raise SetupError(
                "Recording environment changed outside this operation; preserve it before recovery."
            )
        market = self.inspect_marketplace()
        plugin = self.installed_plugin(market)
        if plugin and operation["origin"]["state"] is None and not operation["pluginIntent"]:
            raise SetupError(
                "A plugin appeared without a recorded installation attempt; preserve the registration and review operation.json before retrying."
            )

        def identity(row: dict[str, Any] | None) -> tuple[Any, Any, Any] | None:
            return (
                (row.get("pluginId"), row.get("version"), row.get("enabled", True)) if row else None
            )

        expected_plugin = (PLUGIN, operation["candidate"]["version"], True)
        if plugin and identity(plugin) not in (
            identity(operation["origin"]["plugin"]),
            expected_plugin,
        ):
            raise SetupError(
                "Plugin metadata changed outside the recorded operation; preserve it before recovery."
            )
        if self.args.dry_run:
            return {"status": "dry-run", "plan": report}
        self.confirm(report)
        self.acquire_operation_lock()
        self.expect_bytes(self.pending_path, self.pending_raw)
        # Check again after confirmation before changing any resource.
        for entry in reversed(operation["writes"]):
            path = self.managed_operation_path(entry["path"])
            before, current = self.decode_before(entry["before"]), self.bytes_at(path)
            if current == before:
                continue
            if not self.matches_recorded_write(current, entry["after"]):
                raise SetupError(
                    f"Recovery path changed during confirmation: {path}. Preserve it and retry."
                )
            if before is None:
                path.unlink()
            else:
                self.atomic_bytes(path, before, expected=current)
        if operation["environmentIntent"] and self.environment() == str(self.trace_root):
            previous = operation["origin"]["environment"]
            self.command(
                [self.launchctl, "unsetenv", ENV_KEY]
                if previous is None
                else [self.launchctl, "setenv", ENV_KEY, previous]
            )
        directories = {
            parent
            for entry in operation["writes"]
            for parent in Path(entry["path"]).parents
            if self.bundle.source_path == parent or self.bundle.source_path in parent.parents
        }
        directories.update(
            self.operation_directory(value, operation["traceRoot"])
            for value in operation["directories"]
        )
        for directory in sorted(directories, key=lambda p: len(p.parts), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass
        operation["writes"] = []
        operation["directories"] = []
        operation["environmentIntent"] = False
        operation["phase"] = "recovered"
        self.save_pending()
        self.journal = []
        self.created_dirs = []
        if operation["origin"]["receipt"] is None:
            # A first-install source may already be registered. Recreate its
            # verified catalog before asking Codex to inspect that registration.
            self.recording_intents = True
            self.bundled("plan")
            self.bundled("apply", self.write_managed, self.ensure_directory)
            self.retain_bundle_source()
        return None

    def ensure_directory(self, path: Path) -> None:
        safe_path(path)
        if path.exists():
            if not path.is_dir():
                raise SetupError(f"Expected a directory: {path}")
            return
        missing = []
        current = path
        while not current.exists():
            missing.append(current)
            current = current.parent
        for directory in reversed(missing):
            if self.recording_intents and self.pending is not None:
                try:
                    owned_directory = self.operation_directory(str(directory), str(self.trace_root))
                except SetupError:
                    owned_directory = None
                if (
                    owned_directory is not None
                    and str(directory) not in self.pending["directories"]
                ):
                    self.pending["directories"].append(str(directory))
                    self.save_pending()
            directory.mkdir(mode=0o700)
            self.created_dirs.append(directory)

    def atomic_bytes(self, path: Path, data: bytes, expected: Any = UNSET) -> None:
        safe_path(path)
        self.ensure_directory(path.parent)
        fd, temporary = tempfile.mkstemp(prefix=".dsh-setup-", dir=path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            safe_path(path)
            if expected is not UNSET:
                self.expect_bytes(path, expected)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        if path.read_bytes() != data:
            raise SetupError(f"Configuration changed while being written: {path}")

    def write_managed(self, path: Path, data: bytes, expected: Any = UNSET) -> None:
        safe_path(path)
        previous = self.bytes_at(path)
        if expected is not UNSET and previous != expected:
            raise SetupError(f"Configuration changed since inspection; preserving {path}")
        if previous == data:
            return
        if previous is not None:
            backup = self.state_path.parent / "backups" / f"{path.name}.{digest(previous)}.bak"
            backup_bytes = self.bytes_at(backup)
            if backup_bytes is None:
                self.atomic_bytes(backup, previous, expected=None)
            elif backup_bytes != previous:
                raise SetupError(f"Preserving conflicting recovery backup: {backup}")
        self.journal.append((path, previous, digest(data)))
        self.record_write(path, previous, data)
        self.atomic_bytes(path, data, expected=previous)

    def rollback(self, previous_env: str | None, set_env: bool) -> None:
        for path, previous, expected in reversed(self.journal):
            if expected is None:
                if path.exists() or path.is_symlink():
                    self.warnings.append(f"Concurrent edit preserved during rollback: {path}")
                elif previous is not None:
                    self.atomic_bytes(path, previous, expected=None)
                continue
            if self.bytes_at(path) == previous:
                continue
            if path.is_symlink() or not path.is_file() or digest(path.read_bytes()) != expected:
                self.warnings.append(f"Concurrent edit preserved during rollback: {path}")
                continue
            if previous is None:
                path.unlink()
            else:
                self.atomic_bytes(path, previous, expected=path.read_bytes())
        if set_env:
            if self.environment() == str(self.trace_root):
                self.command(
                    [self.launchctl, "unsetenv", ENV_KEY]
                    if previous_env is None
                    else [self.launchctl, "setenv", ENV_KEY, previous_env]
                )
            else:
                self.warnings.append("Concurrent recording environment edit preserved.")
        for directory in reversed(self.created_dirs):
            try:
                directory.rmdir()
            except OSError:
                pass

    def remove_managed(self, path: Path, expected: bytes | None) -> None:
        safe_path(path)
        self.expect_bytes(path, expected)
        current = path.read_bytes()
        self.journal.append((path, current, None))
        self.record_write(path, current, None)
        path.unlink()
