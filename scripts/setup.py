#!/usr/bin/env python3
"""Install, inspect, or remove dsh-trace-extension's macOS/Codex setup.

Only the official Codex CLI edits Codex's configuration. This helper owns a small
state file and an optional login LaunchAgent; recorded conversations are never
deleted. All runtime dependencies are in Python's standard library.
"""

import argparse
import base64
import contextlib
import hashlib
import importlib.util
import json
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

OWNER = "dsh-trace-extension"
STATE_VERSION = 1
MARKETPLACE = "rollout-local"
PLUGIN = "codex-dsh-trace@rollout-local"
ENV_KEY = "CODEX_ROLLOUT_TRACE_ROOT"
LABEL = "io.dsh-trace-extension.codex-recording"
UNSET = object()


class SetupError(Exception):
    """A preflight, configuration, or command error with an actionable message."""


_RUNTIME_CHECKS = None
_TERMINAL_UI = None


def terminal_ui():
    global _TERMINAL_UI
    if _TERMINAL_UI is None:
        path = Path(__file__).with_name("installer_ui.py")
        spec = importlib.util.spec_from_file_location("dsh_installer_ui", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _TERMINAL_UI = module
    return _TERMINAL_UI


def runtime_checks():
    global _RUNTIME_CHECKS
    if _RUNTIME_CHECKS is None:
        path = Path(__file__).with_name("installer_checks.py")
        if not path.is_file():
            raise SetupError(
                "The npm package lacks installation checks. Reinstall the reviewed package."
            )
        spec = importlib.util.spec_from_file_location("dsh_installer_checks", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _RUNTIME_CHECKS = module
    return _RUNTIME_CHECKS


def digest(data):
    return hashlib.sha256(data).hexdigest()


def absolute(value, home=None):
    value = os.fspath(value)
    if home is not None and (value == "~" or value.startswith("~/")):
        value = str(home) + value[1:]
    return Path(os.path.abspath(os.path.expanduser(value)))


def safe_path(path):
    """Refuse symlinks, including symlinked ancestors, before managed writes."""
    path = Path(path)
    for candidate in (path, *path.parents):
        if candidate.is_symlink():
            raise SetupError(f"Refusing symlinked setup path: {candidate}")
    return path


class System:
    def run(self, command, env=None):
        return subprocess.run(command, capture_output=True, text=True, check=False, env=env)

    def which(self, command, path=None):
        return shutil.which(command, path=path)

    def probe_backend(self, python, cache, expected, timeout=5.0, limit=128 * 1024):
        checks = runtime_checks()
        try:
            return checks.probe_backend(python, cache, expected, timeout, limit)
        except checks.CheckError as exc:
            return {"status": "unknown", "reason": str(exc)}


class Installer:
    def __init__(self, args, system=None, platform=None, home=None, environ=None):
        self.args = args
        self.system = system or System()
        self.platform = sys.platform if platform is None else platform
        self.environ = dict(os.environ if environ is None else environ)
        self.ui = terminal_ui().InstallerUI(
            environ=self.environ,
            json_mode=args.json,
            no_animation=args.no_animation,
            verbose=args.verbose,
        )
        self.home = absolute(home or self.environ.get("HOME", Path.home()))
        self.codex_home = absolute(
            args.codex_home or self.environ.get("CODEX_HOME", self.home / ".codex"), self.home
        )
        self.state_path = self.codex_home / OWNER / "setup.json"
        self.pending_path = self.state_path.with_name("operation.json")
        self.trace_root = absolute(args.trace_root or self.codex_home / "rollout-traces", self.home)
        self.launch_path = self.home / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        self.codex = None
        self.launchctl = None
        self.commands_done = []
        self.journal = []
        self.created_dirs = []
        self.warnings = []
        self.state = None
        self.last_state_bytes = None
        self.bundle = None
        self.bundle_error = None
        self.install_source = None
        self.observed_source = None
        self.bundle_retained = False
        self.pending = None
        self.pending_raw = None
        self.recording_intents = False
        self.operation_lock = None

    def initialize_bundle(self):
        if self.bundle is not None:
            return
        module_path = Path(__file__).resolve().with_name("installer_bundle.py")
        if not module_path.is_file():
            raise SetupError("The npm package is incomplete. Reinstall dsh-trace-extension.")
        spec = importlib.util.spec_from_file_location("dsh_trace_installer_bundle", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.bundle_error = module.BundleError
        try:
            self.bundle = module.BundledMarketplace(
                absolute(self.args.bundle, self.home), self.codex_home, sys.executable
            )
        except self.bundle_error as exc:
            raise SetupError(str(exc)) from exc
        self.install_source = str(self.bundle.source_path)

    def bundled(self, method, *args, **kwargs):
        try:
            return getattr(self.bundle, method)(*args, **kwargs)
        except self.bundle_error as exc:
            raise SetupError(str(exc)) from exc

    def bundle_source(self, value):
        return bool(
            self.bundle is not None
            and isinstance(value, str)
            and Path(value).is_absolute()
            and absolute(value, self.home) == self.bundle.source_path
        )

    def require_verified_bundle(self, require_current=False, check_runtime=True):
        result = self.bundled(
            "verify", require_current=require_current, check_runtime=check_runtime
        )
        if not result.get("valid"):
            raise SetupError(
                "Preserving the managed npm source: " + result.get("reason", "verification failed")
            )
        return result

    def retain_bundle_source(self):
        paths = self.bundled("commit_source")
        self.journal = [entry for entry in self.journal if entry[0] not in paths]
        self.bundle_retained = True

    def bytes_at(self, path):
        safe_path(path)
        if not path.exists():
            return None
        if not path.is_file():
            raise SetupError(f"Preserving non-file configuration path: {path}")
        if path.stat().st_size > 128 * 1024 * 1024:
            raise SetupError(f"Preserving oversized configuration file: {path}")
        return path.read_bytes()

    def managed_operation_path(self, value):
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

    def acquire_operation_lock(self):
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

    def release_operation_lock(self):
        if self.operation_lock is not None:
            os.close(self.operation_lock)
            self.operation_lock = None

    def operation_busy(self):
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

    def operation_lock_path(self):
        return (
            self.home / "Library/Caches" / OWNER / (digest(str(self.codex_home).encode()) + ".lock")
        )

    def operation_directory(self, value, trace_root):
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
    def decode_before(value):
        if value is None:
            return None
        if not isinstance(value, str) or len(value) > 4 * 1024 * 1024:
            raise SetupError("Invalid recovery snapshot; preserve operation.json for review.")
        try:
            return base64.b64decode(value, validate=True)
        except ValueError as exc:
            raise SetupError("Invalid recovery snapshot encoding.") from exc

    @staticmethod
    def matches_recorded_write(current, checksum):
        return (
            current is None
            if checksum is None
            else current is not None and digest(current) == checksum
        )

    def load_pending(self):
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

    def save_pending(self):
        data = (json.dumps(self.pending, sort_keys=True, indent=2) + "\n").encode()
        self.atomic_bytes(self.pending_path, data, expected=self.pending_raw)
        self.pending_raw = data

    def begin_operation(self, plan):
        if self.pending is None:

            def encode(value):
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
                    if plan["_environment_owned"]
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

    def record_write(self, path, before, after):
        if not self.recording_intents:
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

    def recover_operation(self):
        operation = self.pending
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

        def identity(row):
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

    def expect_bytes(self, path, expected):
        if self.bytes_at(path) != expected:
            raise SetupError(
                f"Configuration changed since inspection; preserving {path}. Rerun setup."
            )

    def command(self, command, required=True):
        environment = dict(self.environ)
        environment["HOME"] = str(self.home)
        environment["CODEX_HOME"] = str(self.codex_home)
        result = self.system.run([str(part) for part in command], env=environment)
        if required and result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise SetupError(f"Command failed: {' '.join(map(str, command))}\n{detail}")
        return result

    def json_command(self, command):
        result = self.command(command)
        try:
            value = json.loads(result.stdout)
        except (TypeError, ValueError) as exc:
            raise SetupError("Codex returned invalid JSON; update/check the Codex CLI.") from exc
        if not isinstance(value, dict):
            raise SetupError("Unsupported Codex CLI response; expected a JSON object.")
        return value

    def load_state(self):
        self.last_state_bytes = self.bytes_at(self.state_path)
        if self.last_state_bytes is None:
            return None
        try:
            state = json.loads(self.last_state_bytes)
        except (ValueError, OSError) as exc:
            raise SetupError(f"Preserving unreadable setup state: {self.state_path}") from exc
        if (
            not isinstance(state, dict)
            or set(state)
            != {
                "owner",
                "stateVersion",
                "client",
                "source",
                "traceRoot",
                "environmentOwned",
                "previousEnvironment",
                "pluginOwned",
                "launchAgent",
                "bundle",
            }
            or state.get("owner") != OWNER
            or type(state.get("stateVersion")) is not int
            or state.get("stateVersion") != STATE_VERSION
            or state.get("client") != "codex"
            or not isinstance(state.get("traceRoot"), str)
            or not Path(state["traceRoot"]).is_absolute()
            or not isinstance(state.get("environmentOwned"), bool)
            or not isinstance(state.get("pluginOwned"), bool)
            or state.get("source") != str(self.state_path.parent / "marketplace")
            or state.get("previousEnvironment") is not None
            and not isinstance(state["previousEnvironment"], str)
        ):
            raise SetupError(f"Preserving unrecognized setup state: {self.state_path}")
        agent = state.get("launchAgent")
        if agent is not None and (
            not isinstance(agent, dict)
            or set(agent) != {"path", "sha256"}
            or agent.get("path") != str(self.launch_path)
            or not isinstance(agent.get("sha256"), str)
            or len(agent["sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in agent["sha256"])
        ):
            raise SetupError("Setup state contains an unrecognized managed resource.")
        bundle = state.get("bundle")
        if (
            not isinstance(bundle, dict)
            or set(bundle) != {"source", "receipt", "version"}
            or bundle.get("source") != str(self.state_path.parent / "marketplace")
            or bundle.get("receipt")
            != str(self.state_path.parent / "marketplace/.dsh-trace-bundle.json")
            or not isinstance(bundle.get("version"), str)
        ):
            raise SetupError("Setup state contains an unrecognized bundled marketplace.")
        return state

    def check_dependencies(self):
        if self.platform != "darwin":
            raise SetupError("This installer currently supports macOS and Codex only.")
        if sys.version_info < (3, 9):
            raise SetupError("Python 3.9 or newer is required.")
        search_path = self.environ.get("PATH", os.defpath)
        self.codex = self.system.which("codex", path=search_path)
        self.launchctl = self.system.which("launchctl", path=search_path)
        if not self.codex:
            raise SetupError(
                "Codex CLI was not found. Install Codex or add it to PATH, then retry."
            )
        if not self.launchctl or not Path(self.launchctl).is_absolute():
            raise SetupError("An absolute launchctl executable is required on macOS.")
        version = self.command([self.codex, "--version"]).stdout.strip()
        self.command([self.codex, "plugin", "add", "--help"])
        return version

    def installed_plugin(self, marketplace_exists=True):
        if not marketplace_exists or not self.codex_home.exists():
            return None
        data = self.json_command(
            [self.codex, "plugin", "list", "--marketplace", MARKETPLACE, "--json"]
        )
        rows = data.get("installed")
        if not isinstance(rows, list):
            raise SetupError("Unsupported Codex plugin list response.")
        plugin = next(
            (
                row
                for row in rows
                if isinstance(row, dict)
                and row.get("pluginId") == PLUGIN
                and row.get("installed") is True
            ),
            None,
        )
        if plugin and not isinstance(plugin.get("enabled", True), bool):
            raise SetupError(
                "Codex returned an unknown plugin enabled state; check/update the CLI before setup."
            )
        return plugin

    def inspect_marketplace(self):
        safe_path(self.codex_home)
        if not self.codex_home.exists():
            # Codex refuses metadata commands for an absent explicit CODEX_HOME.
            # Discovery must stay read-only; setup creates this root after consent.
            self.observed_source = None
            return False
        if not self.codex_home.is_dir():
            raise SetupError(f"Expected a Codex configuration directory: {self.codex_home}")
        data = self.json_command([self.codex, "plugin", "marketplace", "list", "--json"])
        rows = data.get("marketplaces")
        if not isinstance(rows, list):
            raise SetupError("Unsupported Codex marketplace list response.")
        matches = [r for r in rows if isinstance(r, dict) and r.get("name") == MARKETPLACE]
        if len(matches) > 1:
            raise SetupError("Several marketplaces use the expected name; preserving them.")
        self.observed_source = None
        if not matches:
            return False
        row = matches[0]
        metadata = row.get("marketplaceSource")
        if not isinstance(metadata, dict):
            raise SetupError("Unrecognized marketplace metadata; preserving configuration.")
        source = metadata.get("source") or row.get("root")
        if not self.bundle_source(source):
            raise SetupError(
                f"Marketplace {MARKETPLACE!r} uses a different or unknown source; "
                "it will not be overwritten."
            )
        self.observed_source = source
        return True

    def environment(self):
        result = self.command([self.launchctl, "getenv", ENV_KEY], required=False)
        if result.returncode not in (0, 1):
            raise SetupError("Unable to inspect the current macOS login recording environment.")
        return (
            result.stdout.rstrip("\n")
            if not result.returncode and result.stdout.rstrip("\n")
            else None
        )

    def desired_agent(self):
        return plistlib.dumps(
            {
                "Label": LABEL,
                "ProgramArguments": [self.launchctl, "setenv", ENV_KEY, str(self.trace_root)],
                "RunAtLoad": True,
            },
            sort_keys=True,
        )

    def check_owned_agent(self):
        safe_path(self.launch_path)
        agent = self.state.get("launchAgent") if self.state else None
        if self.launch_path.exists():
            if not self.launch_path.is_file():
                raise SetupError(f"Preserving non-file LaunchAgent path: {self.launch_path}")
            if not agent or digest(self.launch_path.read_bytes()) != agent["sha256"]:
                raise SetupError(
                    f"LaunchAgent is not owned by this setup or was edited; preserving {self.launch_path}"
                )

    def cache_report(self, plugin, expected=None):
        if not plugin:
            return {
                "status": "not-installed",
                "verified": False,
                "missing": [],
                "modified": [],
                "extra": [],
            }
        version = plugin.get("version")
        if (
            not isinstance(version, str)
            or not all(c in "0123456789." for c in version)
            or len(version.split(".")) != 3
        ):
            return {
                "status": "unknown",
                "verified": False,
                "reason": "Codex did not return a supported installed version.",
                "missing": [],
                "modified": [],
                "extra": [],
            }
        root = self.codex_home / "plugins/cache" / MARKETPLACE / "codex-dsh-trace" / version
        if expected is None:
            receipt = self.bundled("active_receipt")
            if not receipt or receipt["version"] != version:
                return {
                    "status": "unknown",
                    "verified": False,
                    "reason": "Installed version does not match the retained source.",
                    "missing": [],
                    "modified": [],
                    "extra": [],
                }
            expected = self.bundled("cache_files", receipt)
        return runtime_checks().inspect_cache(root, version, expected)

    def repair_cache(self, plugin, plan):
        target = (
            self.codex_home
            / "plugins/cache"
            / MARKETPLACE
            / "codex-dsh-trace"
            / self.bundle.version
        )
        owned = self.pending["origin"]["pluginOwned"]
        previous = (
            plan["_cache_expected"]
            if plan["_plugin"] and plan["_plugin"].get("version") == self.bundle.version
            else {}
        )
        for name, data in self.bundled("candidate_files").items():
            path = target / name
            before = self.bytes_at(path)
            if before == data:
                continue
            if not owned or (before is not None and digest(before) != previous.get(name)):
                raise SetupError(
                    f"Preserving edited or unowned installed file: {path}. Save and move the reviewed conflicting copy aside, then rerun setup; recordings are unchanged."
                )
            self.ensure_directory(path.parent)
            self.write_managed(path, data, expected=before)
        report = self.cache_report(
            plugin, {name: digest(data) for name, data in self.bundled("candidate_files").items()}
        )
        if not report["verified"]:
            raise SetupError(
                "Installed files could not be verified. Keep operation.json and rerun setup after reviewing doctor."
            )

    def preflight(self):
        version = self.check_dependencies()
        self.state = self.load_state()
        self.initialize_bundle()
        if self.pending and not self.args.trace_root:
            self.trace_root = absolute(self.pending["traceRoot"])
        elif self.state and not self.args.trace_root:
            self.trace_root = absolute(self.state["traceRoot"])
        for path in (self.codex_home, self.trace_root, self.state_path.parent):
            safe_path(path)
            if path.exists() and not path.is_dir():
                raise SetupError(f"Expected a directory; preserving existing path: {path}")
        self.check_owned_agent()
        marketplace_exists = self.inspect_marketplace()
        plugin = self.installed_plugin(marketplace_exists)
        receipt = self.bundled("active_receipt", allow_missing=True)
        if self.state and (
            receipt is None or self.state["bundle"]["version"] != receipt["version"]
        ):
            raise SetupError(
                "Setup state and retained source disagree; preserve both and review doctor before retrying."
            )
        expected_cache = self.bundled("cache_files", receipt) if receipt else {}
        if (
            plugin
            and plugin.get("version") == self.bundle.version
            and self.pending
            and self.pending["pluginIntent"]
        ):
            expected_cache = {
                name: digest(data) for name, data in self.bundled("candidate_files").items()
            }
        cache = self.cache_report(plugin, expected_cache) if plugin else self.cache_report(None)
        plugin_owned = bool(
            (self.state and self.state["pluginOwned"])
            or (self.pending and self.pending["origin"]["pluginOwned"])
        )
        if plugin and not plugin_owned:
            raise SetupError(
                "The installed plugin has no verified setup ownership. Preserve it and use a clean Codex profile, or review its registration manually before setup."
            )
        if plugin and (cache["modified"] or cache["status"] == "unknown"):
            raise SetupError(
                f"Installed cache is edited or cannot be verified: {cache.get('path', 'unknown')}. Run doctor --json, preserve the listed paths, and move only reviewed conflicting copies aside before retrying."
            )
        if plugin and plugin.get("version") != self.bundle.version and cache["extra"]:
            raise SetupError(
                f"Installed cache contains unowned files at {cache['path']}; preserve and review those files before updating."
            )
        if not plugin or plugin.get("version") != self.bundle.version:
            target_cache = self.cache_report(
                {"version": self.bundle.version},
                {name: digest(data) for name, data in self.bundled("candidate_files").items()},
            )
            if (
                target_cache["modified"]
                or target_cache["extra"]
                or target_cache["status"] == "unknown"
            ):
                raise SetupError(
                    f"Preserving an edited or unowned target cache at {target_cache.get('path', 'unknown')}. Review those paths before installing this release."
                )
        recovery_files = {}
        source_recovery_cache = None
        if receipt and self.bundle.missing_files and plugin_owned:
            old_plugin = plugin
            if plugin and plugin.get("version") != receipt["version"] and self.pending:
                old_plugin = self.pending["origin"]["plugin"]
            if old_plugin and old_plugin.get("version") == receipt["version"]:
                old_cache = self.cache_report(old_plugin, self.bundled("cache_files", receipt))
                if old_cache["verified"] and not old_cache["extra"]:
                    source_recovery_cache = (
                        old_plugin,
                        self.bundled("cache_files", receipt),
                        old_cache,
                    )
                    prefix = receipt["activeBundle"] + "/plugins/codex-dsh-trace/"
                    for name in self.bundle.missing_files:
                        if not name.startswith(prefix):
                            continue
                        cached = Path(old_cache["path"]) / name[len(prefix) :]
                        data = self.bytes_at(cached)
                        if data is None or digest(data) != receipt["files"][name]:
                            raise SetupError(
                                f"Old cache changed while preparing source recovery: {cached}. Preserve it before retrying."
                            )
                        recovery_files[name] = data
        bundle_plan = self.bundled("plan", recovery_files=recovery_files)
        current_env = self.environment()
        old_owned = bool(
            self.state
            and self.state.get("environmentOwned")
            and current_env == self.state.get("traceRoot")
        )
        if current_env not in (None, str(self.trace_root)) and not old_owned:
            raise SetupError(
                f"{ENV_KEY} already points elsewhere; preserving its current value. "
                "Use the same --trace-root or review the existing recording configuration."
            )
        commands = []
        if not marketplace_exists:
            commands.append(
                [self.codex, "plugin", "marketplace", "add", self.install_source, "--json"]
            )
        if (
            not plugin
            or not plugin.get("enabled", True)
            or plugin.get("version") != self.bundle.version
        ):
            commands.append([self.codex, "plugin", "add", PLUGIN, "--json"])
        agent_bytes = None if self.args.no_persist else self.desired_agent()
        changes = []
        if not self.codex_home.exists():
            changes.append({"action": "create-codex-config-root", "path": str(self.codex_home)})
        changes.extend(bundle_plan["changes"])
        if plugin and (
            cache["missing"]
            or (receipt and receipt["pythonExecutable"] != self.bundle.python_executable)
        ):
            changes.append(
                {
                    "action": "repair-owned-installed-files",
                    "path": cache.get("path", ""),
                    "missing": cache["missing"],
                    "reason": "python-changed"
                    if receipt and receipt["pythonExecutable"] != self.bundle.python_executable
                    else "missing-files",
                    "previousPython": receipt["pythonExecutable"] if receipt else None,
                    "pythonExecutable": self.bundle.python_executable,
                }
            )
        if not self.trace_root.exists():
            changes.append({"action": "create-recording-directory", "path": str(self.trace_root)})
        if current_env != str(self.trace_root):
            changes.append(
                {"action": "set-login-environment", "name": ENV_KEY, "value": str(self.trace_root)}
            )
        if agent_bytes is not None:
            if not self.launch_path.exists() or self.launch_path.read_bytes() != agent_bytes:
                changes.append(
                    {"action": "write-login-launch-agent", "path": str(self.launch_path)}
                )
        elif self.launch_path.exists():
            changes.append({"action": "remove-owned-launch-agent", "path": str(self.launch_path)})
        return {
            "client": "codex",
            "codexVersion": version,
            "source": self.install_source,
            "traceRoot": str(self.trace_root),
            "stateFile": str(self.state_path),
            "customTraceRoot": self.trace_root != self.codex_home / "rollout-traces",
            "persistentLoginSetup": not self.args.no_persist,
            "commands": commands,
            "changes": changes,
            "restartRequired": True,
            "nativeVerified": False,
            "bundledPluginVersion": self.bundle.version,
            "notes": [
                "Recording is opt-in and may contain prompts, code, credentials, and tool output.",
                "Fully quit and reopen Codex, then run a new task; opening the panel does not enable recording.",
                "The login LaunchAgent prepares future login sessions; ordering with auto-started Codex is not verified.",
            ],
            "_environment": current_env,
            "_plugin": plugin,
            "_agent": agent_bytes,
            "_environment_owned": old_owned,
            "_state_bytes": self.last_state_bytes,
            "_agent_before": self.bytes_at(self.launch_path),
            "_marketplace_exists": marketplace_exists,
            "_observed_source": self.observed_source,
            "_cache": cache,
            "_cache_expected": expected_cache,
            "_source_recovery_cache": source_recovery_cache,
        }

    def revalidate(self, plan):
        self.expect_bytes(self.state_path, plan["_state_bytes"])
        self.expect_bytes(self.launch_path, plan["_agent_before"])
        self.bundled("revalidate")
        if self.environment() != plan["_environment"]:
            raise SetupError(
                "Recording environment changed since inspection; preserving it. Rerun setup."
            )
        marketplace_exists = self.inspect_marketplace()
        if marketplace_exists != plan["_marketplace_exists"]:
            raise SetupError("Marketplace registration changed since inspection. Rerun setup.")
        if self.observed_source != plan["_observed_source"]:
            raise SetupError("Marketplace source changed since inspection. Rerun setup.")
        if self.installed_plugin(marketplace_exists) != plan["_plugin"]:
            raise SetupError("Plugin installation changed since inspection. Rerun setup.")
        if (
            plan["_plugin"]
            and self.cache_report(plan["_plugin"], plan["_cache_expected"]) != plan["_cache"]
        ):
            raise SetupError(
                "Installed files changed since inspection; preserve them and rerun setup."
            )
        if plan["_source_recovery_cache"]:
            old_plugin, expected, observed = plan["_source_recovery_cache"]
            if self.cache_report(old_plugin, expected) != observed:
                raise SetupError(
                    "Old cache changed since source recovery was inspected; preserve it before retrying."
                )

    def ensure_directory(self, path):
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
            if self.recording_intents:
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

    def atomic_bytes(self, path, data, expected=UNSET):
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

    def write_managed(self, path, data, expected=UNSET):
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

    def rollback(self, previous_env, set_env):
        for path, previous, expected in reversed(self.journal):
            if expected is None:
                if path.exists() or path.is_symlink():
                    self.warnings.append(f"Concurrent edit preserved during rollback: {path}")
                else:
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

    def remove_managed(self, path, expected):
        safe_path(path)
        self.expect_bytes(path, expected)
        self.journal.append((path, path.read_bytes(), None))
        self.record_write(path, path.read_bytes(), None)
        path.unlink()

    def setup(self):
        try:
            return self.apply_setup()
        finally:
            self.release_operation_lock()

    def apply_setup(self):
        self.ui.header()
        with self.ui.stage("Check setup"):
            self.check_dependencies()
            self.initialize_bundle()
            pending = self.load_pending()
            if not pending:
                plan = self.preflight()
        if pending:
            # Recovery can ask for confirmation. Never redraw over that prompt.
            recovered = self.recover_operation()
            if recovered is not None:
                return recovered
            with self.ui.stage("Check setup"):
                plan = self.preflight()
        public = {k: v for k, v in plan.items() if not k.startswith("_")}
        if self.args.dry_run:
            return {"status": "dry-run", "plan": public}
        self.confirm(public)
        self.revalidate(plan)
        self.acquire_operation_lock()
        self.revalidate(plan)
        env_changed = False
        try:
            configuration_root_was_missing = not self.codex_home.exists()
            self.ensure_directory(self.codex_home)
            if configuration_root_was_missing:
                # Real Codex cannot inspect sources until its root exists. Now
                # also catch project-scoped sources before registering anything.
                self.revalidate(plan)
            self.begin_operation(plan)
            with (
                self.ui.stage("Set up Codex Trace")
                if plan["changes"] or plan["commands"]
                else contextlib.nullcontext()
            ):
                self.bundled("apply", self.write_managed, self.ensure_directory)
                if plan["_marketplace_exists"]:
                    self.retain_bundle_source()
                self.ensure_directory(self.trace_root)
                if plan["_agent"] is not None:
                    self.write_managed(
                        self.launch_path, plan["_agent"], expected=plan["_agent_before"]
                    )
                elif self.launch_path.exists():
                    # Delaying removal until after success keeps failed setup reversible.
                    pass
                if plan["_environment"] != str(self.trace_root):
                    self.pending["environmentIntent"] = True
                    self.save_pending()
                    self.command([self.launchctl, "setenv", ENV_KEY, str(self.trace_root)])
                    env_changed = True
                for command in plan["commands"]:
                    # Once registration is attempted, Codex may retain this path.
                    self.retain_bundle_source()
                    if command[1:3] == ["plugin", "add"]:
                        self.pending["pluginIntent"] = True
                        self.save_pending()
                    self.command(command)
                    self.commands_done.append(command)
            plugin = self.installed_plugin()
            if not plugin or not plugin.get("enabled", True):
                raise SetupError(
                    "Codex did not report the plugin installed and enabled after setup."
                )
            if plugin.get("version") != self.bundle.version:
                raise SetupError(
                    f"Codex reported plugin version {plugin.get('version')!r}, expected {self.bundle.version!r}. "
                    "The source was preserved; rerun setup after reviewing the CLI state."
                )
            with (
                self.ui.stage("Verify plugin files")
                if plan["changes"] or plan["commands"]
                else contextlib.nullcontext()
            ):
                self.require_verified_bundle(require_current=True)
                self.repair_cache(plugin, plan)
            if self.args.no_persist and self.launch_path.exists():
                self.check_owned_agent()
                self.remove_managed(self.launch_path, expected=plan["_agent_before"])
            self.expect_bytes(self.launch_path, plan["_agent"])
            if self.environment() != str(self.trace_root):
                raise SetupError("Recording environment changed during setup; preserving it.")
            state = {
                "owner": OWNER,
                "stateVersion": STATE_VERSION,
                "client": "codex",
                "source": self.install_source,
                "traceRoot": str(self.trace_root),
                "environmentOwned": self.pending["origin"]["environmentOwned"],
                "previousEnvironment": self.pending["origin"]["previousEnvironment"],
                "pluginOwned": self.pending["origin"]["pluginOwned"],
                "launchAgent": {
                    "path": str(self.launch_path),
                    "sha256": digest(plan["_agent"]),
                }
                if plan["_agent"] is not None
                else None,
            }
            state["bundle"] = {
                "source": str(self.bundle.source_path),
                "receipt": str(self.bundle.receipt_path),
                "version": self.bundle.version,
            }
            data = (json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
            self.write_managed(self.state_path, data, expected=plan["_state_bytes"])
            self.expect_bytes(self.pending_path, self.pending_raw)
            self.pending_path.unlink()
            self.pending = self.pending_raw = None
            self.recording_intents = False
        except (SetupError, OSError) as exc:
            try:
                self.rollback(plan["_environment"], env_changed)
            except (SetupError, OSError) as rollback_error:
                self.warnings.append(f"Rollback needs review: {rollback_error}")
            if self.bundle_retained:
                self.warnings.append(
                    "The verified bundled marketplace was retained because Codex may refer to it. "
                    "Keep operation.json and rerun the same npm version to recover this installation."
                )
            partial = ""
            if self.commands_done:
                partial = (
                    "\nSome Codex CLI commands completed and may remain configured. "
                    "They were not undone by restoring the whole Codex configuration. "
                    "Review the error and rerun setup."
                )
            if self.pending is not None:
                partial += f"\nRetry: npx dsh-trace-extension@{self.bundle.version} setup. Recovery record: {self.pending_path}."
            raise SetupError(str(exc) + partial) from exc
        changed = bool(plan["changes"] or plan["commands"] or self.journal)
        return {
            "status": "configured" if changed else "unchanged",
            "plan": public,
            "pluginVersion": plugin.get("version"),
            "next": "Fully quit and reopen Codex, run a new task, then open Codex Trace.",
            "nativeVerified": False,
        }

    def confirm(self, plan):
        ui = getattr(self, "ui", None)
        compact = (
            ui is not None and ui.enhanced and self.args.action == "setup" and plan.get("stateFile")
        )
        if (
            "commands" in plan
            and "changes" in plan
            and not plan["commands"]
            and not plan["changes"]
        ):
            if compact and ui.verbose:
                ui.summary(plan, details=True)
            return
        if compact:
            ui.summary(plan)
        else:
            print_plan(plan, file=sys.stderr)
        if self.args.yes:
            return
        try:
            with (
                open("/dev/tty", "r", encoding="utf-8") as terminal_in,
                open("/dev/tty", "w", encoding="utf-8") as terminal_out,
            ):
                prompt = (
                    "Apply setup? [y/N/d=details] "
                    if compact
                    else "Apply this dsh-trace-extension setup? [y/N] "
                )
                while True:
                    terminal_out.write(prompt)
                    terminal_out.flush()
                    answer = terminal_in.readline().strip().lower()
                    if compact and answer == "d":
                        if not ui.details_shown:
                            ui.summary(plan, details=True)
                        continue
                    break
        except OSError as exc:
            raise SetupError(
                "No interactive terminal. Review --dry-run, then pass --yes to apply."
            ) from exc
        if answer not in ("y", "yes"):
            raise SetupError("Setup cancelled; no changes applied.")

    def doctor(self):
        version = self.check_dependencies()
        self.initialize_bundle()
        pending = self.load_pending()
        if pending:
            active = self.operation_busy()
            return {
                "status": "needs-setup",
                "client": "codex",
                "codexVersion": version,
                "pluginInstalled": None,
                "pluginEnabled": None,
                "loginEnvironmentMatches": self.environment() == pending["traceRoot"],
                "launchAgent": "unknown-pending-recovery",
                "compatibleRecordingBundles": 0,
                "unsupportedRecordingBundles": 0,
                "traceRoot": pending["traceRoot"],
                "nativeVerified": False,
                "bundledMarketplace": {"valid": False, "status": "pending-recovery"},
                "installedContent": {"verified": False, "status": "unknown-pending-recovery"},
                "backend": {
                    "status": "not-run",
                    "reason": "Finish the recorded operation before probing.",
                },
                "recovery": {
                    "path": str(self.pending_path),
                    "version": pending["candidate"]["version"],
                    "active": active,
                },
                "next": "Another installation is running; wait for it to finish, then run doctor again."
                if active
                else f"Run npx dsh-trace-extension@{pending['candidate']['version']} setup --dry-run, then setup to recover the recorded operation. Unknown or edited writes will be preserved.",
            }
        self.state = self.load_state()
        market = self.inspect_marketplace()
        plugin = self.installed_plugin(market)
        if self.state and not self.args.trace_root:
            self.trace_root = absolute(self.state["traceRoot"])
        safe_path(self.trace_root)
        environment = self.environment()
        agent = self.state.get("launchAgent") if self.state else None
        agent_status = "not-managed"
        if agent:
            safe_path(self.launch_path)
            agent_status = (
                "unchanged"
                if self.launch_path.is_file()
                and digest(self.launch_path.read_bytes()) == agent["sha256"]
                else "missing-or-edited"
            )
        elif self.launch_path.exists() or self.launch_path.is_symlink():
            agent_status = "foreign"
        recordings = 0
        unsupported = 0
        if self.trace_root.is_dir():
            for entry in self.trace_root.iterdir():
                if entry.is_symlink() or not entry.is_dir():
                    continue
                manifest = entry / "manifest.json"
                events = entry / "trace.jsonl"
                if manifest.is_symlink() or events.is_symlink():
                    continue
                try:
                    if manifest.stat().st_size > 65536:
                        continue
                    data = json.loads(manifest.read_text(encoding="utf-8"))
                    if data.get("schema_version") in (1, 2) and events.is_file():
                        recordings += 1
                    else:
                        unsupported += 1
                except (OSError, ValueError, AttributeError):
                    continue
        configured = bool(
            plugin
            and plugin.get("enabled", True)
            and environment == str(self.trace_root)
            and (not agent or agent_status == "unchanged")
        )
        bundle_report = self.bundled("verify")
        installed_version = plugin.get("version") if plugin else None
        bundle_report["pluginVersionMatches"] = bool(
            bundle_report.get("valid") and installed_version == bundle_report.get("version")
        )
        bundle_report["marketplaceMatches"] = market
        cache = (
            self.cache_report(plugin)
            if bundle_report["valid"]
            else {"verified": False, "status": "unknown-source-not-verified"}
        )
        backend = {"status": "not-run", "reason": "Verified, owned installed files are required."}
        if cache["verified"] and self.state and self.state["pluginOwned"] and not cache["extra"]:
            if bundle_report["pythonExecutable"] != str(Path(sys.executable).resolve()):
                backend = {
                    "status": "unknown",
                    "reason": "Pinned Python differs from this checked interpreter. Rerun setup to select this interpreter before probing.",
                }
            elif hasattr(self.system, "probe_backend"):
                try:
                    backend = self.system.probe_backend(
                        bundle_report["pythonExecutable"],
                        Path(cache["path"]),
                        self.bundled("cache_files"),
                    )
                    if (
                        backend.get("status") == "verified"
                        and backend.get("version") != installed_version
                    ):
                        backend = {
                            "status": "failed",
                            "reason": "Backend version does not match the installed plugin.",
                        }
                except (OSError, SetupError, subprocess.SubprocessError) as exc:
                    backend = {
                        "status": "unknown",
                        "reason": f"Backend probe could not complete safely: {exc}",
                    }
            else:
                backend = {
                    "status": "unknown",
                    "reason": "This system adapter does not provide a bounded backend probe.",
                }
        elif cache.get("extra"):
            backend = {
                "status": "unknown",
                "reason": "Unowned installed files may affect execution; preserve and review them before probing.",
            }
        configured = (
            bool(self.state)
            and configured
            and bundle_report["pluginVersionMatches"]
            and market
            and cache["verified"]
            and backend["status"] not in ("failed", "timeout", "output-limit")
        )
        return {
            "status": "configured-needs-native-check" if configured else "needs-setup",
            "client": "codex",
            "codexVersion": version,
            "pluginInstalled": bool(plugin),
            "pluginEnabled": bool(plugin and plugin.get("enabled", True)),
            "loginEnvironmentMatches": environment == str(self.trace_root),
            "launchAgent": agent_status,
            "compatibleRecordingBundles": recordings,
            "unsupportedRecordingBundles": unsupported,
            "traceRoot": str(self.trace_root),
            "nativeVerified": False,
            "bundledMarketplace": bundle_report,
            "installedContent": cache,
            "backend": backend,
            "candidateVersion": self.bundle.version,
            "setupStateVerified": bool(self.state),
            "next": "Open a new recorded task in Codex Trace to verify native readiness. Old bundles do not prove the running app has reloaded."
            if configured
            else "Review these checks, then run npx dsh-trace-extension@latest setup --dry-run and setup. Edited or unowned paths require review; they are not overwritten.",
        }

    def uninstall(self):
        try:
            return self.apply_uninstall()
        finally:
            self.release_operation_lock()

    def apply_uninstall(self):
        self.check_dependencies()
        self.initialize_bundle()
        if self.load_pending():
            raise SetupError(
                f"Finish the recorded setup before uninstalling: npx dsh-trace-extension@{self.pending['candidate']['version']} setup. Keep {self.pending_path}; recordings are unchanged."
            )
        self.state = self.load_state()
        if not self.state:
            return {"status": "not-managed", "recordingsDeleted": False}
        bundle_before = self.require_verified_bundle(check_runtime=False)
        state_before = self.last_state_bytes
        self.check_owned_agent()
        agent_before = self.bytes_at(self.launch_path)
        environment = self.environment()
        env_owned = self.state.get("environmentOwned")
        conflicts = []
        if env_owned and environment not in (None, self.state["traceRoot"]):
            conflicts.append("Recording environment changed after setup and will be preserved.")
        commands = []
        plugin_owned = self.state.get("pluginOwned")
        marketplace_exists = self.inspect_marketplace()
        plugin_before = self.installed_plugin(marketplace_exists) if plugin_owned else None
        if plugin_before:
            cache = self.cache_report(plugin_before)
            if cache["status"] == "unknown" or cache["modified"] or cache["extra"]:
                raise SetupError(
                    f"Preserving edited or unowned installed files at {cache.get('path', 'unknown')}. Review doctor --json and preserve/move those files before uninstalling."
                )
        if plugin_before:
            commands.append([self.codex, "plugin", "remove", PLUGIN, "--json"])
        plan = {
            "client": "codex",
            "commands": commands,
            "removeOwnedLaunchAgent": bool(
                self.state.get("launchAgent") and self.launch_path.exists()
            ),
            "restoreOwnedEnvironment": bool(env_owned and not conflicts),
            "recordingsDeleted": False,
            "marketplaceRemoved": False,
            "bundleSourceRetained": str(self.bundle.source_path),
            "notes": conflicts + ["Recordings and unrelated Codex settings are preserved."],
        }
        plan["notes"].append(
            "The verified bundled source is retained because the marketplace or a preserved plugin may refer to it."
        )
        if self.args.dry_run:
            return {"status": "dry-run", "plan": plan}
        self.confirm(plan)
        self.acquire_operation_lock()
        self.expect_bytes(self.state_path, state_before)
        self.expect_bytes(self.launch_path, agent_before)
        if self.require_verified_bundle(check_runtime=False) != bundle_before:
            raise SetupError("The managed npm source changed since inspection; preserving it.")
        if self.environment() != environment:
            raise SetupError("Recording environment changed since inspection; preserving it.")
        if plugin_owned and (
            self.inspect_marketplace() != marketplace_exists
            or self.installed_plugin(marketplace_exists) != plugin_before
        ):
            raise SetupError("Plugin installation changed since inspection; preserving it.")
        if plugin_before and self.cache_report(plugin_before) != cache:
            raise SetupError(
                "Installed files changed during confirmation; preserving them before uninstall."
            )
        for command in commands:
            result = self.command(command, required=False)
            if result.returncode:
                raise SetupError(
                    "Codex plugin removal failed; recording setup remains intact.\n" + result.stderr
                )
        current_environment = self.environment()
        if plan["restoreOwnedEnvironment"] and current_environment == self.state["traceRoot"]:
            previous = self.state.get("previousEnvironment")
            self.command(
                [self.launchctl, "unsetenv", ENV_KEY]
                if previous is None
                else [self.launchctl, "setenv", ENV_KEY, previous]
            )
        elif plan["restoreOwnedEnvironment"] and current_environment != environment:
            conflicts.append("Recording environment changed during uninstall and was preserved.")
        if plan["removeOwnedLaunchAgent"]:
            self.check_owned_agent()
            self.launch_path.unlink()
        # The state itself must also remain the same after preflight.
        if self.load_state() != self.state:
            raise SetupError("Setup state changed during uninstall; preserving the state file.")
        self.state_path.unlink()
        return {
            "status": "uninstalled",
            "plan": plan,
            "warnings": conflicts,
            "recordingsDeleted": False,
        }


def print_plan(plan, file=None):
    file = sys.stdout if file is None else file
    print("dsh-trace-extension — Codex setup plan", file=file)
    for command in plan.get("commands", []):
        print(f"  Run: {shlex.join(str(part) for part in command)}", file=file)
    for change in plan.get("changes", []):
        target = change.get("path") or change.get("value") or change.get("name", "")
        print(f"  {change['action']}: {target}", file=file)
    if plan.get("stateFile"):
        print(f"  State: {plan['stateFile']}", file=file)
    if "persistentLoginSetup" in plan:
        print(
            "  Login setup: "
            + ("enabled" if plan["persistentLoginSetup"] else "current login only"),
            file=file,
        )
    if plan.get("removeOwnedLaunchAgent"):
        print("  Remove the unchanged helper-owned login LaunchAgent.", file=file)
    if plan.get("restoreOwnedEnvironment"):
        print("  Restore the helper-owned login recording environment.", file=file)
    for note in plan.get("notes", []):
        print(f"  Note: {note}", file=file)


def print_result(result):
    status = result["status"]
    if status == "dry-run":
        print_plan(result["plan"])
        print("Dry run only: no installation or recording settings were changed.")
    elif status in ("configured", "unchanged"):
        print(f"dsh-trace-extension: {status}.")
        print(f"Recording folder: {result['plan']['traceRoot']}")
        print(f"Next: {result['next']}")
    elif status in ("needs-setup", "configured-needs-native-check"):
        print(f"dsh-trace-extension: {status}.")
        enabled = result["pluginEnabled"]
        plugin_status = (
            "unknown" if enabled is None else "enabled" if enabled else "missing or disabled"
        )
        print(
            f"Plugin: {plugin_status}; "
            f"login environment: {'matches' if result['loginEnvironmentMatches'] else 'not configured'}; "
            f"login LaunchAgent: {result['launchAgent']}."
        )
        print(
            f"Recording bundles: {result['compatibleRecordingBundles']} compatible, "
            f"{result['unsupportedRecordingBundles']} unsupported. Native readiness is not verified."
        )
        print(f"Next: {result['next']}")
        bundle = result.get("bundledMarketplace", {})
        if bundle.get("status") != "not-used":
            print(f"Bundled plugin source: {bundle.get('status', 'unknown')}.")
        installed = result.get("installedContent", {})
        backend = result.get("backend", {})
        print(
            f"Installed content: {installed.get('status', 'unknown')}; backend probe: {backend.get('status', 'unknown')}."
        )
        if backend.get("reason"):
            print(f"Backend: {backend['reason']}")
        if installed.get("missing") or installed.get("modified") or installed.get("extra"):
            print(
                "Review doctor --json for missing, modified or unowned paths before applying setup."
            )
    elif status == "uninstalled":
        print(
            "Removed the unchanged helper-owned setup. Recordings and marketplace were preserved."
        )
        if result.get("plan", {}).get("bundleSourceRetained"):
            print(f"Bundled source retained: {result['plan']['bundleSourceRetained']}")
    elif status == "not-managed":
        print("No helper-owned setup found. Nothing was removed.")
    for warning in result.get("warnings", []):
        print(f"Warning: {warning}")


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument(
        "action", choices=("setup", "doctor", "uninstall"), nargs="?", default="setup"
    )
    value.add_argument("--client", choices=("codex",), default="codex")
    value.add_argument(
        "--bundle", required=True, help="Path to the npm package's verified plugin payload"
    )
    value.add_argument("--trace-root")
    value.add_argument("--codex-home")
    value.add_argument(
        "--yes", action="store_true", help="Apply the reviewed plan without prompting"
    )
    value.add_argument(
        "--dry-run", action="store_true", help="Inspect and print a plan without writing"
    )
    value.add_argument(
        "--json", action="store_true", help="Write only the final JSON result to stdout"
    )
    value.add_argument(
        "--no-persist",
        action="store_true",
        help="Configure this login only, without a login LaunchAgent",
    )
    value.add_argument("--no-animation", action="store_true", help="Use static terminal progress")
    value.add_argument("--verbose", action="store_true", help="Show full installation details")
    return value


def main(argv=None, **dependencies):
    args = parser().parse_args(argv)
    installer = Installer(args, **dependencies)
    try:
        result = getattr(installer, args.action)()
        if installer.warnings:
            result.setdefault("warnings", []).extend(installer.warnings)
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        elif not installer.ui.result(result):
            print_result(result)
        return 0
    except (SetupError, OSError) as exc:
        result = {"status": "error", "error": str(exc), "warnings": installer.warnings}
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(f"Error: {exc}", file=sys.stderr)
            for warning in installer.warnings:
                print(f"Warning: {warning}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        message = "Interrupted. Rerun setup to check or recover any installation changes."
        if args.json:
            print(json.dumps({"status": "error", "error": message, "warnings": installer.warnings}))
        else:
            print(f"\n{message}", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
