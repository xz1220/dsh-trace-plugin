#!/usr/bin/env python3
"""Install, inspect, or remove dsh-trace-extension's macOS/Codex setup.

Only the official Codex CLI edits Codex's configuration. This helper owns a small
state file and an optional login LaunchAgent; recorded conversations are never
deleted. All runtime dependencies are in Python's standard library.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

# Support direct execution (`python3 .../installer/setup.py`) as well as package imports.
_INSTALLER_DIR = str(Path(__file__).resolve().parent)
if _INSTALLER_DIR not in sys.path:
    sys.path.insert(0, _INSTALLER_DIR)

import installer_bundle  # noqa: E402
import installer_checks  # noqa: E402
import installer_ui  # noqa: E402
from installer_journal import (  # noqa: E402
    ENV_KEY,
    LABEL,
    MARKETPLACE,
    OWNER,
    PLUGIN,
    STATE_VERSION,
    UNSET,
    OperationJournalMixin,
    SetupError,
    absolute,
    digest,
    safe_path,
)

__all__ = [
    "ENV_KEY",
    "LABEL",
    "MARKETPLACE",
    "OWNER",
    "PLUGIN",
    "STATE_VERSION",
    "UNSET",
    "Installer",
    "SetupError",
    "System",
    "absolute",
    "digest",
    "main",
    "parser",
    "print_plan",
    "print_result",
    "runtime_checks",
    "safe_path",
    "terminal_ui",
]


def terminal_ui() -> Any:
    return installer_ui


def runtime_checks() -> Any:
    return installer_checks


class System:
    def run(
        self, command: list[str], env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(command, capture_output=True, text=True, check=False, env=env)

    def which(self, command: str, path: str | None = None) -> str | None:
        return shutil.which(command, path=path)

    def probe_backend(
        self,
        python: str,
        cache: Path,
        expected: dict[str, str],
        timeout: float = 5.0,
        limit: int = 128 * 1024,
    ) -> dict[str, Any]:
        checks = runtime_checks()
        try:
            return checks.probe_backend(python, cache, expected, timeout, limit)
        except checks.CheckError as exc:
            return {"status": "unknown", "reason": str(exc)}


class Installer(OperationJournalMixin):
    def __init__(
        self,
        args: argparse.Namespace,
        system: Any = None,
        platform: str | None = None,
        home: Path | str | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
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
        self.home = absolute(
            home if home is not None else (self.environ.get("HOME") or Path.home())
        )
        self.codex_home = absolute(
            args.codex_home or self.environ.get("CODEX_HOME", self.home / ".codex"), self.home
        )
        self.state_path = self.codex_home / OWNER / "setup.json"
        self.pending_path = self.state_path.with_name("operation.json")
        self.trace_root = absolute(args.trace_root or self.codex_home / "rollout-traces", self.home)
        self.launch_path = self.home / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        self.codex: str | None = None
        self.launchctl: str | None = None
        self.commands_done: list[list[Any]] = []
        self.journal: list[tuple[Path, bytes | None, str | None]] = []
        self.created_dirs: list[Path] = []
        self.warnings: list[str] = []
        self.state: dict[str, Any] | None = None
        self.last_state_bytes: bytes | None = None
        self.bundle: Any = None
        self.bundle_error: type[Exception] = installer_bundle.BundleError
        self.install_source: str | None = None
        self.observed_source: str | None = None
        self.bundle_retained = False
        self.pending: dict[str, Any] | None = None
        self.pending_raw: bytes | None = None
        self.recording_intents = False
        self.operation_lock: int | None = None

    def initialize_bundle(self) -> None:
        if self.bundle is not None:
            return
        self.bundle_error = installer_bundle.BundleError
        try:
            self.bundle = installer_bundle.BundledMarketplace(
                absolute(self.args.bundle, self.home), self.codex_home, sys.executable
            )
        except self.bundle_error as exc:
            raise SetupError(str(exc)) from exc
        self.install_source = str(self.bundle.source_path)

    def bundled(self, method: str, *args: Any, **kwargs: Any) -> Any:
        try:
            return getattr(self.bundle, method)(*args, **kwargs)
        except self.bundle_error as exc:
            raise SetupError(str(exc)) from exc

    def bundle_source(self, value: Any) -> bool:
        return bool(
            self.bundle is not None
            and isinstance(value, str)
            and Path(value).is_absolute()
            and absolute(value, self.home) == self.bundle.source_path
        )

    def require_verified_bundle(
        self, require_current: bool = False, check_runtime: bool = True
    ) -> dict[str, Any]:
        result: dict[str, Any] = self.bundled(
            "verify", require_current=require_current, check_runtime=check_runtime
        )
        if not result.get("valid"):
            raise SetupError(
                "Preserving the managed npm source: " + result.get("reason", "verification failed")
            )
        return result

    def retain_bundle_source(self) -> None:
        paths = self.bundled("commit_source")
        self.journal = [entry for entry in self.journal if entry[0] not in paths]
        self.bundle_retained = True

    def command(self, command: list[Any], required: bool = True) -> Any:
        environment = dict(self.environ)
        environment["HOME"] = str(self.home)
        environment["CODEX_HOME"] = str(self.codex_home)
        result = self.system.run([str(part) for part in command], env=environment)
        if required and result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise SetupError(f"Command failed: {' '.join(map(str, command))}\n{detail}")
        return result

    def json_command(self, command: list[Any]) -> dict[str, Any]:
        result = self.command(command)
        try:
            value = json.loads(result.stdout)
        except (TypeError, ValueError) as exc:
            raise SetupError("Codex returned invalid JSON; update/check the Codex CLI.") from exc
        if not isinstance(value, dict):
            raise SetupError("Unsupported Codex CLI response; expected a JSON object.")
        return value

    def load_state(self) -> dict[str, Any] | None:
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

    def check_dependencies(self) -> str:
        if self.platform != "darwin":
            raise SetupError("This installer currently supports macOS and Codex only.")
        if sys.version_info < (3, 9):  # noqa: UP036
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
        version = str(self.command([self.codex, "--version"]).stdout).strip()
        self.command([self.codex, "plugin", "add", "--help"])
        return version

    def installed_plugin(self, marketplace_exists: bool = True) -> dict[str, Any] | None:
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

    def inspect_marketplace(self) -> bool:
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

    def environment(self) -> str | None:
        result = self.command([self.launchctl, "getenv", ENV_KEY], required=False)
        if result.returncode not in (0, 1):
            raise SetupError("Unable to inspect the current macOS login recording environment.")
        value = str(result.stdout).rstrip("\n")
        return value if not result.returncode and value else None

    def desired_agent(self) -> bytes:
        return plistlib.dumps(
            {
                "Label": LABEL,
                "ProgramArguments": [self.launchctl, "setenv", ENV_KEY, str(self.trace_root)],
                "RunAtLoad": True,
            },
            sort_keys=True,
        )

    def check_owned_agent(self) -> None:
        safe_path(self.launch_path)
        agent = self.state.get("launchAgent") if self.state else None
        if self.launch_path.exists():
            if not self.launch_path.is_file():
                raise SetupError(f"Preserving non-file LaunchAgent path: {self.launch_path}")
            if not agent or digest(self.launch_path.read_bytes()) != agent["sha256"]:
                raise SetupError(
                    f"LaunchAgent is not owned by this setup or was edited; preserving {self.launch_path}"
                )

    def cache_report(
        self, plugin: dict[str, Any] | None, expected: dict[str, str] | None = None
    ) -> dict[str, Any]:
        if not plugin:
            return {
                "status": "not-installed",
                "verified": False,
                "missing": [],
                "modified": [],
                "extra": [],
            }
        version = plugin.get("version")
        if not isinstance(version, str) or not installer_bundle.VERSION.fullmatch(version):
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
        return dict(runtime_checks().inspect_cache(root, version, expected))

    def repair_cache(self, plugin: dict[str, Any], plan: dict[str, Any]) -> None:
        target = (
            self.codex_home
            / "plugins/cache"
            / MARKETPLACE
            / "codex-dsh-trace"
            / self.bundle.version
        )
        assert self.pending is not None
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

    def preflight(self) -> dict[str, Any]:
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
        recovery_files: dict[str, bytes] = {}
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
        commands: list[list[Any]] = []
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
        changes: list[dict[str, Any]] = []
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
            "recordingDirectoryChanged": bool(
                self.state and self.state["traceRoot"] != str(self.trace_root)
            ),
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

    def revalidate(self, plan: dict[str, Any]) -> None:
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

    def setup(self) -> dict[str, Any]:
        try:
            return self.apply_setup()
        finally:
            self.release_operation_lock()

    def apply_setup(self) -> dict[str, Any]:
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
            assert self.pending is not None
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
            state: dict[str, Any] = {
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
            pruned = self.bundled("prune_superseded_bundles", retain=2)
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
        result: dict[str, Any] = {
            "status": "configured" if changed else "unchanged",
            "plan": public,
            "pluginVersion": plugin.get("version"),
            "next": "Fully quit and reopen Codex, run a new task, then open Codex Trace.",
            "nativeVerified": False,
        }
        if pruned:
            result["prunedBundles"] = pruned
        return result

    def confirm(self, plan: dict[str, Any]) -> None:
        ui = getattr(self, "ui", None)
        compact = bool(
            ui is not None and ui.enhanced and self.args.action == "setup" and plan.get("stateFile")
        )
        if (
            "commands" in plan
            and "changes" in plan
            and not plan["commands"]
            and not plan["changes"]
        ):
            if compact and ui is not None and ui.verbose:
                ui.summary(plan, details=True)
            return
        if compact and ui is not None:
            ui.summary(plan)
        else:
            print_plan(plan, file=sys.stderr)
        if self.args.yes:
            return
        try:
            with (
                open("/dev/tty", encoding="utf-8") as terminal_in,
                open("/dev/tty", "w", encoding="utf-8") as terminal_out,
            ):
                prompt = (
                    ui.prefix("[?_?]") + "Apply setup? [y/N/d=details] "
                    if compact and ui is not None
                    else "Apply this dsh-trace-extension setup? [y/N] "
                )
                while True:
                    terminal_out.write(prompt)
                    terminal_out.flush()
                    answer = terminal_in.readline().strip().lower()
                    if compact and ui is not None and answer == "d":
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

    def doctor(self) -> dict[str, Any]:
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
        bundle_report: dict[str, Any] = self.bundled("verify")
        installed_version = plugin.get("version") if plugin else None
        bundle_report["pluginVersionMatches"] = bool(
            bundle_report.get("valid") and installed_version == bundle_report.get("version")
        )
        bundle_report["marketplaceMatches"] = market
        cache: dict[str, Any] = (
            self.cache_report(plugin)
            if bundle_report["valid"]
            else {"verified": False, "status": "unknown-source-not-verified"}
        )
        backend: dict[str, Any] = {
            "status": "not-run",
            "reason": "Verified, owned installed files are required.",
        }
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

    def uninstall(self) -> dict[str, Any]:
        try:
            return self.apply_uninstall()
        finally:
            self.release_operation_lock()

    def apply_uninstall(self) -> dict[str, Any]:
        self.check_dependencies()
        self.initialize_bundle()
        if self.load_pending():
            assert self.pending is not None
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
        conflicts: list[str] = []
        if env_owned and environment not in (None, self.state["traceRoot"]):
            conflicts.append("Recording environment changed after setup and will be preserved.")
        commands: list[list[Any]] = []
        plugin_owned = self.state.get("pluginOwned")
        marketplace_exists = self.inspect_marketplace()
        plugin_before = self.installed_plugin(marketplace_exists) if plugin_owned else None
        cache: dict[str, Any] = {}
        if plugin_before:
            cache = self.cache_report(plugin_before)
            if cache["status"] == "unknown" or cache["modified"] or cache["extra"]:
                raise SetupError(
                    f"Preserving edited or unowned installed files at {cache.get('path', 'unknown')}. Review doctor --json and preserve/move those files before uninstalling."
                )
        if plugin_before:
            commands.append([self.codex, "plugin", "remove", PLUGIN, "--json"])
        plan: dict[str, Any] = {
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


def print_plan(plan: dict[str, Any], file: Any = None) -> None:
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


def print_result(result: dict[str, Any]) -> None:
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


def parser() -> argparse.ArgumentParser:
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


def main(argv: Sequence[str] | None = None, **dependencies: Any) -> int:
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
        elif installer.ui.enhanced:
            for line in str(exc).splitlines():
                installer.ui.notice("Error: " + line, "[!_!]")
            for warning in installer.warnings:
                installer.ui.notice("Warning: " + warning, "[!_!]")
        else:
            print(f"Error: {exc}", file=sys.stderr)
            for warning in installer.warnings:
                print(f"Warning: {warning}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        message = "Interrupted. Rerun setup to check or recover any installation changes."
        if args.json:
            print(json.dumps({"status": "error", "error": message, "warnings": installer.warnings}))
        elif installer.ui.enhanced:
            installer.ui.notice(message, "[!_!]")
        else:
            print(f"\n{message}", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
