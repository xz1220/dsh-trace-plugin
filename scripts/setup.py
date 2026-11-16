#!/usr/bin/env python3
"""Install, inspect, or remove dsh-trace-extension's macOS/Codex setup.

Only the official Codex CLI edits Codex's configuration. This helper owns a small
state file and an optional login LaunchAgent; recorded conversations are never
deleted. All runtime dependencies are in Python's standard library.
"""

import argparse
import hashlib
import json
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

OWNER = "dsh-trace-extension"
STATE_VERSION = 1
DEFAULT_SOURCE = "xz1220/dsh-trace-plugin"
MARKETPLACE = "rollout-local"
PLUGIN = "codex-dsh-trace@rollout-local"
ENV_KEY = "CODEX_ROLLOUT_TRACE_ROOT"
LABEL = "io.dsh-trace-extension.codex-recording"
UNSET = object()


class SetupError(Exception):
    """A preflight, configuration, or command error with an actionable message."""


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


def git_identity(source):
    source = str(source).rstrip("/")
    if source.startswith("git@github.com:"):
        source = source[len("git@github.com:") :]
    elif "://" in source:
        parsed = urlparse(source)
        if parsed.username or parsed.password:
            raise SetupError("Use credential-free repository URLs and your Git credential helper.")
        if parsed.hostname != "github.com":
            return source
        source = parsed.path.lstrip("/")
    if source.endswith(".git"):
        source = source[:-4]
    return source.lower()


class System:
    def run(self, command, env=None):
        return subprocess.run(command, capture_output=True, text=True, check=False, env=env)

    def which(self, command, path=None):
        return shutil.which(command, path=path)


class Installer:
    def __init__(self, args, system=None, platform=None, home=None, environ=None):
        self.args = args
        self.system = system or System()
        self.platform = sys.platform if platform is None else platform
        self.environ = dict(os.environ if environ is None else environ)
        self.home = absolute(home or self.environ.get("HOME", Path.home()))
        self.codex_home = absolute(
            args.codex_home or self.environ.get("CODEX_HOME", self.home / ".codex"), self.home
        )
        self.state_path = self.codex_home / OWNER / "setup.json"
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

    def bytes_at(self, path):
        safe_path(path)
        if not path.exists():
            return None
        if not path.is_file():
            raise SetupError(f"Preserving non-file configuration path: {path}")
        return path.read_bytes()

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
            or state.get("owner") != OWNER
            or state.get("stateVersion") != STATE_VERSION
            or state.get("client") != "codex"
            or not isinstance(state.get("traceRoot"), str)
            or not Path(state["traceRoot"]).is_absolute()
            or not isinstance(state.get("environmentOwned"), bool)
            or not isinstance(state.get("pluginOwned"), bool)
            or not isinstance(state.get("source"), str)
            or not state["source"]
            or state.get("ref") is not None
            and not isinstance(state["ref"], str)
            or state.get("previousEnvironment") is not None
            and not isinstance(state["previousEnvironment"], str)
        ):
            raise SetupError(f"Preserving unrecognized setup state: {self.state_path}")
        agent = state.get("launchAgent")
        if agent is not None and (
            not isinstance(agent, dict)
            or agent.get("path") != str(self.launch_path)
            or not isinstance(agent.get("sha256"), str)
            or len(agent["sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in agent["sha256"])
        ):
            raise SetupError("Setup state contains an unrecognized managed resource.")
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
        if not marketplace_exists:
            return None
        data = self.json_command(
            [self.codex, "plugin", "list", "--marketplace", MARKETPLACE, "--json"]
        )
        rows = data.get("installed")
        if not isinstance(rows, list):
            raise SetupError("Unsupported Codex plugin list response.")
        return next(
            (
                row
                for row in rows
                if isinstance(row, dict)
                and row.get("pluginId") == PLUGIN
                and row.get("installed") is True
            ),
            None,
        )

    def local_source(self, source):
        value = str(source)
        if value.startswith(("/", ".", "~")) or Path(value).exists():
            return absolute(value, self.home)
        return None

    def source_matches(self, existing, requested_source=None):
        requested_source = self.args.source if requested_source is None else requested_source
        requested_local = self.local_source(requested_source)
        existing_local = self.local_source(existing)
        if existing_local:
            safe_path(existing_local)
            if requested_local and existing_local == requested_local:
                return True
            catalog = existing_local / ".agents/plugins/marketplace.json"
            try:
                data = json.loads(catalog.read_text(encoding="utf-8"))
                if data.get("name") != MARKETPLACE or not any(
                    p.get("name") == "codex-dsh-trace" for p in data.get("plugins", [])
                ):
                    return False
            except (OSError, ValueError, TypeError, AttributeError):
                return False
            result = self.command(
                ["git", "-C", str(existing_local), "config", "--get", "remote.origin.url"],
                required=False,
            )
            if requested_local:
                requested = self.command(
                    ["git", "-C", str(requested_local), "config", "--get", "remote.origin.url"],
                    required=False,
                )
                return (
                    not result.returncode
                    and not requested.returncode
                    and bool(result.stdout.strip())
                    and git_identity(result.stdout.strip())
                    == git_identity(requested.stdout.strip())
                )
            return (
                not result.returncode
                and not requested_local
                and git_identity(result.stdout.strip()) == git_identity(requested_source)
            )
        return not requested_local and git_identity(existing) == git_identity(requested_source)

    def inspect_marketplace(self, requested_source=None):
        requested_source = self.args.source if requested_source is None else requested_source
        local = self.local_source(requested_source)
        if local:
            safe_path(local)
            try:
                catalog = json.loads(
                    (local / ".agents/plugins/marketplace.json").read_text(encoding="utf-8")
                )
            except (OSError, ValueError) as exc:
                raise SetupError("Local source is missing a valid marketplace catalog.") from exc
            if (
                not isinstance(catalog, dict)
                or catalog.get("name") != MARKETPLACE
                or not any(
                    isinstance(p, dict) and p.get("name") == "codex-dsh-trace"
                    for p in catalog.get("plugins", [])
                )
            ):
                raise SetupError("Local source does not contain the expected Codex plugin.")
        else:
            git_identity(requested_source)
        data = self.json_command([self.codex, "plugin", "marketplace", "list", "--json"])
        rows = data.get("marketplaces")
        if not isinstance(rows, list):
            raise SetupError("Unsupported Codex marketplace list response.")
        matches = [r for r in rows if isinstance(r, dict) and r.get("name") == MARKETPLACE]
        if len(matches) > 1:
            raise SetupError("Several marketplaces use the expected name; preserving them.")
        if matches:
            row = matches[0]
            metadata = row.get("marketplaceSource") or {}
            if not isinstance(metadata, dict):
                raise SetupError(
                    "Unsupported marketplace source metadata; preserving configuration."
                )
            source = metadata.get("source") or row.get("root")
            if not source or not self.source_matches(source, requested_source):
                raise SetupError(
                    f"Marketplace {MARKETPLACE!r} belongs to a different or unknown source; "
                    "it will not be overwritten."
                )
            return True
        return False

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

    def preflight(self):
        version = self.check_dependencies()
        self.state = self.load_state()
        if self.state and not self.args.trace_root:
            self.trace_root = absolute(self.state["traceRoot"])
        for path in (self.codex_home, self.trace_root, self.state_path.parent):
            safe_path(path)
            if path.exists() and not path.is_dir():
                raise SetupError(f"Expected a directory; preserving existing path: {path}")
        self.check_owned_agent()
        marketplace_exists = self.inspect_marketplace()
        plugin = self.installed_plugin(marketplace_exists)
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
            command = [self.codex, "plugin", "marketplace", "add", self.args.source]
            if self.args.ref and not self.local_source(self.args.source):
                command += ["--ref", self.args.ref]
            commands.append(command + ["--json"])
        if not plugin or not plugin.get("enabled", True):
            commands.append([self.codex, "plugin", "add", PLUGIN, "--json"])
        agent_bytes = None if self.args.no_persist else self.desired_agent()
        changes = []
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
            "source": self.args.source,
            "ref": self.args.ref,
            "traceRoot": str(self.trace_root),
            "stateFile": str(self.state_path),
            "persistentLoginSetup": not self.args.no_persist,
            "commands": commands,
            "changes": changes,
            "restartRequired": True,
            "nativeVerified": False,
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
        }

    def revalidate(self, plan):
        self.expect_bytes(self.state_path, plan["_state_bytes"])
        self.expect_bytes(self.launch_path, plan["_agent_before"])
        if self.environment() != plan["_environment"]:
            raise SetupError(
                "Recording environment changed since inspection; preserving it. Rerun setup."
            )
        marketplace_exists = self.inspect_marketplace()
        if marketplace_exists != plan["_marketplace_exists"]:
            raise SetupError("Marketplace registration changed since inspection. Rerun setup.")
        if self.installed_plugin(marketplace_exists) != plan["_plugin"]:
            raise SetupError("Plugin installation changed since inspection. Rerun setup.")

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
        path.unlink()

    def setup(self):
        plan = self.preflight()
        public = {k: v for k, v in plan.items() if not k.startswith("_")}
        if self.args.dry_run:
            return {"status": "dry-run", "plan": public}
        self.confirm(public)
        self.revalidate(plan)
        env_changed = False
        try:
            self.ensure_directory(self.trace_root)
            if plan["_agent"] is not None:
                self.write_managed(self.launch_path, plan["_agent"], expected=plan["_agent_before"])
            elif self.launch_path.exists():
                # Delaying removal until after success keeps failed setup reversible.
                pass
            if plan["_environment"] != str(self.trace_root):
                self.command([self.launchctl, "setenv", ENV_KEY, str(self.trace_root)])
                env_changed = True
            for command in plan["commands"]:
                self.command(command)
                self.commands_done.append(command)
            plugin = self.installed_plugin()
            if not plugin or not plugin.get("enabled", True):
                raise SetupError(
                    "Codex did not report the plugin installed and enabled after setup."
                )
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
                "source": self.args.source,
                "ref": self.args.ref,
                "traceRoot": str(self.trace_root),
                "environmentOwned": bool(plan["_environment_owned"] or env_changed),
                "previousEnvironment": self.state.get("previousEnvironment")
                if plan["_environment_owned"]
                else plan["_environment"],
                "pluginOwned": bool(
                    (self.state and self.state.get("pluginOwned")) or not plan["_plugin"]
                ),
                "launchAgent": {
                    "path": str(self.launch_path),
                    "sha256": digest(plan["_agent"]),
                }
                if plan["_agent"] is not None
                else None,
            }
            data = (json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
            self.write_managed(self.state_path, data, expected=plan["_state_bytes"])
        except (SetupError, OSError) as exc:
            try:
                self.rollback(plan["_environment"], env_changed)
            except (SetupError, OSError) as rollback_error:
                self.warnings.append(f"Rollback needs review: {rollback_error}")
            partial = ""
            if self.commands_done:
                partial = (
                    "\nSome Codex CLI commands completed and may remain configured. "
                    "They were not undone by restoring the whole Codex configuration. "
                    "Review the error and rerun setup."
                )
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
        print_plan(plan, file=sys.stderr)
        if self.args.yes:
            return
        try:
            with open("/dev/tty", "r+", encoding="utf-8") as terminal:
                terminal.write("Apply this dsh-trace-extension setup? [y/N] ")
                terminal.flush()
                answer = terminal.readline().strip().lower()
        except OSError as exc:
            raise SetupError(
                "No interactive terminal. Review --dry-run, then pass --yes to apply."
            ) from exc
        if answer not in ("y", "yes"):
            raise SetupError("Setup cancelled; no changes applied.")

    def doctor(self):
        version = self.check_dependencies()
        self.state = self.load_state()
        rows = self.json_command([self.codex, "plugin", "marketplace", "list", "--json"])
        market = any(r.get("name") == MARKETPLACE for r in rows.get("marketplaces", []))
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
            "next": "Open a new recorded task in Codex Trace to verify native readiness. Old bundles do not prove the running app has reloaded.",
        }

    def uninstall(self):
        self.check_dependencies()
        self.state = self.load_state()
        if not self.state:
            return {"status": "not-managed", "recordingsDeleted": False}
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
        marketplace_exists = (
            self.inspect_marketplace(self.state["source"]) if plugin_owned else False
        )
        plugin_before = self.installed_plugin(marketplace_exists) if plugin_owned else None
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
            "notes": conflicts + ["Recordings and unrelated Codex settings are preserved."],
        }
        if self.args.dry_run:
            return {"status": "dry-run", "plan": plan}
        self.confirm(plan)
        self.expect_bytes(self.state_path, state_before)
        self.expect_bytes(self.launch_path, agent_before)
        if self.environment() != environment:
            raise SetupError("Recording environment changed since inspection; preserving it.")
        if plugin_owned and (
            self.inspect_marketplace(self.state["source"]) != marketplace_exists
            or self.installed_plugin(marketplace_exists) != plugin_before
        ):
            raise SetupError("Plugin installation changed since inspection; preserving it.")
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
        print(
            f"Plugin: {'enabled' if result['pluginEnabled'] else 'missing or disabled'}; "
            f"login environment: {'matches' if result['loginEnvironmentMatches'] else 'not configured'}; "
            f"login LaunchAgent: {result['launchAgent']}."
        )
        print(
            f"Recording bundles: {result['compatibleRecordingBundles']} compatible, "
            f"{result['unsupportedRecordingBundles']} unsupported. Native readiness is not verified."
        )
        print(f"Next: {result['next']}")
    elif status == "uninstalled":
        print(
            "Removed the unchanged helper-owned setup. Recordings and marketplace were preserved."
        )
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
    value.add_argument("--source", default=DEFAULT_SOURCE)
    value.add_argument("--ref")
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
        else:
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


if __name__ == "__main__":
    raise SystemExit(main())
