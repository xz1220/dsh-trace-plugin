"""Small terminal-only progress display. Never reads or changes an installation."""

import contextlib
import os
import shutil
import sys
import threading
import unicodedata


def safe_text(value):
    return "".join(char if char.isprintable() else "?" for char in str(value))


class InstallerUI:
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

    def __init__(self, stream=None, environ=None, json_mode=False, no_animation=False):
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

    def ink(self, value, code="36"):
        value = safe_text(value)
        return f"\033[{code}m{value}\033[0m" if self.color else value

    def write(self, value):
        # A detached or closed terminal must not change installation behavior.
        try:
            self.stream.write(value)
            self.stream.flush()
        except (OSError, ValueError):
            pass

    def line(self, value=""):
        self.write(value + "\n")

    def progress_line(self, marker, label):
        width = max(1, shutil.get_terminal_size((80, 24)).columns - 1)
        text = f"  {marker}  {safe_text(label)}"
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
    def stage(self, label):
        if not self.enhanced:
            yield
            return
        stop = threading.Event()
        worker = None

        def draw():
            index = 0
            while not stop.wait(0.12):
                self.write(
                    "\r\033[2K" + self.progress_line(self.frames[index % len(self.frames)], label)
                )
                index += 1

        self.write(self.progress_line(self.frames[0], label) + ("" if self.animated else "\n"))
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
            marker = "[o_o] ✓" if completed else "[!_!] ×"
            self.line(self.progress_line(marker, label if completed else f"Stopped: {label}"))

    def header(self, version=None):
        if not self.enhanced:
            return
        self.line()
        self.line("  " + self.ink("[o_o]") + "  " + self.ink("dsh-trace-extension", "1"))
        self.line("         Codex · local recording")
        if version:
            self.line("         Codex · " + safe_text(version))
        self.line()

    def summary(self, plan):
        if not self.enhanced:
            return
        changes = plan.get("changes", [])
        commands = plan.get("commands", [])
        self.line()
        self.line(
            self.ink(
                "  Here's what will change" if changes or commands else "  Already up to date", "1"
            )
        )
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
            self.line("  + " + safe_text(labels.get(action, action.replace("-", " "))))
            target = change.get("path") or change.get("value") or change.get("name")
            if target:
                self.line("    " + safe_text(target))
            if change.get("reason") == "python-changed":
                self.line("    Python runtime changed since your last setup.")
                self.line("    " + safe_text(change["previousPython"]))
                self.line("    → " + safe_text(change["pythonExecutable"]))
            if change.get("missing"):
                self.line(f"    Restore {len(change['missing'])} missing plugin file(s).")
        for command in commands:
            label = (
                "Register the local plugin source"
                if command[1:3] == ["plugin", "marketplace"]
                else "Enable Codex Trace"
            )
            self.line("  + " + label)
            if command[1:3] == ["plugin", "marketplace"]:
                self.line("    " + safe_text(plan.get("source", "")))
        if plan.get("stateFile"):
            self.line("  Settings  " + safe_text(plan["stateFile"]))
        if plan.get("traceRoot"):
            self.line("  Record to " + safe_text(plan["traceRoot"]))
        self.line()
        self.line("  Recordings may include prompts, code, credentials, and tool output.")
        self.line("  Codex must be reopened before new tasks can use these settings.")
        if plan.get("persistentLoginSetup"):
            self.line(
                "  Login setup prepares future sessions; Codex auto-start ordering is unverified."
            )
        self.line()

    def result(self, result):
        if not self.enhanced or result["status"] not in ("configured", "unchanged"):
            return False
        self.line()
        unchanged = result["status"] == "unchanged"
        self.line(
            "  "
            + self.ink("[^_^]")
            + "  "
            + self.ink("Already up to date" if unchanged else "Local setup complete", "1")
        )
        self.line("         Codex Trace · " + safe_text(result.get("pluginVersion", "")))
        self.line()
        self.line("  Recordings  " + safe_text(result["plan"]["traceRoot"]))
        if unchanged:
            self.line("  No installation changes were needed.")
            self.line(
                "  If you haven't reopened Codex since setup, fully quit and reopen it first."
            )
        else:
            self.line("  Fully quit and reopen Codex to load this setup.")
        self.line("  Run a new task, then open Codex Trace in the conversation sidebar.")
        self.line(
            "  Opening the panel alone does not verify that new recordings are being created."
        )
        for warning in result.get("warnings", []):
            self.line("  Warning: " + safe_text(warning))
        self.line()
        return True
