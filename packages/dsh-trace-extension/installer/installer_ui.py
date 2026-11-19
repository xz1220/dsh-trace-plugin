"""Small terminal-only progress display. Never reads or changes an installation."""

from __future__ import annotations

import contextlib
import os
import shlex
import shutil
import sys
import threading
import unicodedata
from collections.abc import Iterator, Mapping, Sequence
from typing import Any


def safe_text(value: Any) -> str:
    return "".join(char if char.isprintable() else "?" for char in str(value))


class InstallerUI:
    marker_width = 9
    frames = (
        "[o_o] ●··",
        "[o_o] ·●·",
        "[o_o] ··●",
        "[o_o] ·●·",
        "[o_o] ●··",
        "[o_o] ·●·",
        "[o_o] ··●",
        "[o_o] ·●·",
        "[o_o] ●··",
        "[o_o] ·●·",
        "[-_-] ··●",
        "[o_o] ·●·",
    )

    def __init__(
        self,
        stream: Any = None,
        environ: Mapping[str, str] | None = None,
        json_mode: bool = False,
        no_animation: bool = False,
        verbose: bool = False,
    ) -> None:
        self.stream = sys.stderr if stream is None else stream
        self.environ = os.environ if environ is None else environ
        self.enhanced = bool(
            not json_mode
            and self.stream.isatty()
            and self.environ.get("TERM", "") != "dumb"
            and not self.environ.get("CI")
        )
        self.animated = bool(
            self.enhanced and not no_animation and not self.environ.get("DSH_TRACE_NO_ANIMATION")
        )
        self.color = self.enhanced and "NO_COLOR" not in self.environ
        self.verbose = verbose
        self.details_shown = False

    def ink(self, value: Any, code: str = "36") -> str:
        text = safe_text(value)
        return f"\033[{code}m{text}\033[0m" if self.color else text

    def write(self, value: str) -> None:
        # A detached or closed terminal must not change installation behavior.
        try:
            self.stream.write(value)
            self.stream.flush()
        except (OSError, ValueError):
            pass

    def line(self, value: str = "") -> None:
        self.write(value + "\n")

    def prefix(self, marker: str) -> str:
        return "  " + safe_text(marker).ljust(self.marker_width) + "  "

    def notice(self, value: Any, face: str = "[o_o]", code: str | None = None) -> None:
        if not self.enhanced:
            return
        text = self.ink(value, code) if code else safe_text(value)
        self.line(self.ink(self.prefix(face)) + text)

    def progress_line(self, marker: str, label: str) -> str:
        width = max(1, shutil.get_terminal_size((80, 24)).columns - 1)
        text = self.prefix(marker) + safe_text(label)
        used = 0
        clipped = []
        for char in text:
            size = (
                0
                if unicodedata.combining(char)
                else 2
                if unicodedata.east_asian_width(char) in "WF"
                else 1
            )
            if used + size > width - 1:
                clipped.append("…")
                break
            clipped.append(char)
            used += size
        text = "".join(clipped)
        # Only color a bounded line, so a long label cannot wrap behind a clear.
        return self.ink(text)

    @contextlib.contextmanager
    def stage(self, label: str) -> Iterator[None]:
        if not self.enhanced:
            yield
            return
        stop = threading.Event()
        worker: threading.Thread | None = None

        def draw() -> None:
            index = 0
            while not stop.wait(0.12):
                self.write(
                    "\r\033[2K" + self.progress_line(self.frames[index % len(self.frames)], label)
                )
                index += 1

        marker = self.frames[0] if self.animated else "[o_o]"
        self.write(self.progress_line(marker, label) + ("" if self.animated else "\n"))
        if self.animated:
            worker = threading.Thread(target=draw, name="dsh-installer-progress", daemon=True)
            try:
                worker.start()
            except RuntimeError:
                worker = None
                self.animated = False
                self.line()
        completed = False
        try:
            yield
            completed = True
        finally:
            stop.set()
            if worker is not None:
                worker.join()
            if self.animated:
                self.write("\r\033[2K")
            if self.animated or not completed:
                marker = "[o_o] ✓" if completed else "[!_!] ×"
                self.line(self.progress_line(marker, label if completed else f"Stopped: {label}"))

    def header(self, version: str | None = None) -> None:
        if not self.enhanced or not self.verbose:
            return
        suffix = " · " + safe_text(version) if version else ""
        self.notice("dsh-trace-extension" + suffix, code="1")

    @staticmethod
    def known_command(command: Sequence[Any], source: str | None = None) -> bool:
        if not command or os.path.basename(str(command[0])) != "codex":
            return False
        parts = list(command)
        return bool(
            (
                len(parts) == 6
                and parts[1:4] == ["plugin", "marketplace", "add"]
                and source
                and parts[4] == source
                and parts[-1] == "--json"
            )
            or (
                len(parts) == 5
                and parts[1:4] == ["plugin", "add", "codex-dsh-trace@rollout-local"]
                and parts[-1] == "--json"
            )
        )

    def summary(self, plan: dict[str, Any], details: bool | None = None) -> None:
        if not self.enhanced:
            return
        expanded = self.verbose if details is None else details
        if expanded:
            self.show_details(plan)
            return
        changes = plan.get("changes", [])
        commands = plan.get("commands", [])
        actions = {change["action"] for change in changes}
        known = {
            "persist-bundled-plugin",
            "repair-owned-installed-files",
            "create-codex-config-root",
            "create-recording-directory",
            "set-login-environment",
            "write-login-launch-agent",
            "remove-owned-launch-agent",
        }
        if actions & {"set-login-environment", "create-recording-directory"}:
            scope = "across logins" if plan.get("persistentLoginSetup") else "for this login"
            self.notice(f"Enable recording {scope} (may include private data).", "[!_!]")
        elif "write-login-launch-agent" in actions:
            self.notice("Prepare recording at login (may include private data).", "[!_!]")
        elif "remove-owned-launch-agent" in actions:
            self.notice("Keep recording for this login only.", "[!_!]")
        if plan.get("traceRoot") and (
            plan.get("customTraceRoot") or plan.get("recordingDirectoryChanged")
        ):
            self.notice("Record to " + safe_text(plan["traceRoot"]))
        for change in changes:
            if change["action"] not in known:
                target = change.get("path") or change.get("value") or change.get("name", "")
                self.notice(safe_text(change["action"]) + ": " + safe_text(target), "[!_!]")
        for command in commands:
            if not self.known_command(command, plan.get("source")):
                self.notice("Run: " + safe_text(shlex.join(str(part) for part in command)), "[!_!]")

    def show_details(self, plan: dict[str, Any]) -> None:
        if not self.enhanced:
            return
        self.details_shown = True
        changes = plan.get("changes", [])
        commands = plan.get("commands", [])
        self.notice("Installation details", "[?_?]", "1")
        labels = {
            "persist-bundled-plugin": "Keep a stable local copy of the plugin",
            "repair-owned-installed-files": "Refresh the installed plugin",
            "create-codex-config-root": "Create the Codex settings directory",
            "create-recording-directory": "Create the recording directory",
            "set-login-environment": "Enable recording for future Codex launches",
            "write-login-launch-agent": "Prepare recording at login",
            "remove-owned-launch-agent": "Remove the helper's login setup",
            "recover-interrupted-setup": "Recover the interrupted installation",
        }
        for change in changes:
            action = change["action"]
            label = safe_text(labels.get(action, action.replace("-", " ")))
            target = change.get("path") or change.get("value") or change.get("name")
            self.notice(label + (": " + safe_text(target) if target else ""))
            if change.get("reason") == "python-changed":
                self.notice(
                    "Python runtime changed: "
                    + safe_text(change["previousPython"])
                    + " → "
                    + safe_text(change["pythonExecutable"])
                )
            if change.get("missing"):
                self.notice(f"Restore {len(change['missing'])} missing plugin file(s).")
        for command in commands:
            self.notice("Run: " + safe_text(shlex.join(str(part) for part in command)))
        if plan.get("stateFile"):
            self.notice("Settings: " + safe_text(plan["stateFile"]))
        if plan.get("traceRoot"):
            self.notice("Record to " + safe_text(plan["traceRoot"]))
        if "persistentLoginSetup" in plan:
            self.notice(
                "Login setup: " + ("enabled" if plan["persistentLoginSetup"] else "this login only")
            )
        self.notice("Recordings may include prompts, code, credentials, and tool output.", "[!_!]")
        self.notice("Codex must be reopened before new tasks can use these settings.", "[>_>]")
        if plan.get("persistentLoginSetup"):
            self.notice(
                "Login setup prepares future sessions; Codex auto-start ordering is unverified."
            )

    def result(self, result: dict[str, Any]) -> bool:
        if not self.enhanced or result["status"] not in ("configured", "unchanged"):
            return False
        unchanged = result["status"] == "unchanged"
        version = result.get("pluginVersion")
        title = "Already up to date" if unchanged else "Local setup complete"
        if version:
            title += " · " + safe_text(version)
        self.notice(title, "[^_^]", "1")
        expanded = self.verbose or self.details_shown
        if (
            expanded
            or result["plan"].get("customTraceRoot")
            or result["plan"].get("recordingDirectoryChanged")
        ):
            self.notice("Recordings: " + safe_text(result["plan"]["traceRoot"]))
        if unchanged:
            self.notice("If you haven't reopened Codex, fully quit and reopen it first.", "[>_>]")
            self.notice("Run a new task → open Codex Trace in the sidebar.", "[>_>]")
        else:
            self.notice("Fully quit and reopen Codex → run a new task → open Codex Trace.", "[>_>]")
        if expanded:
            self.notice(
                "Opening the panel alone does not verify that new recordings are being created."
            )
        for warning in result.get("warnings", []):
            self.notice("Warning: " + safe_text(warning), "[!_!]")
        return True
