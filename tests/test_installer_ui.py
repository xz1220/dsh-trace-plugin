"""Check terminal presentation without touching a real Codex profile."""

import contextlib
import importlib.util
import io
import os
import re
import sys
import tempfile
import threading
import unicodedata
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "installer_ui_fixture", Path(__file__).resolve().parents[1] / "scripts/installer_ui.py"
)
ui_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ui_module
SPEC.loader.exec_module(ui_module)

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
SGR = re.compile(r"\x1b\[[0-9;]*m")


def plain(value):
    return ANSI.sub("", value)


def columns(value):
    return sum(
        0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in "WF" else 1
        for char in value
    )


class TerminalStream(io.StringIO):
    def __init__(self, tty=True):
        super().__init__()
        self.tty = tty
        self.condition = threading.Condition()
        self.refreshes = 0

    def isatty(self):
        return self.tty

    def write(self, value):
        with self.condition:
            result = super().write(value)
            self.refreshes += value.count("\r")
            self.condition.notify_all()
            return result

    def wait_for_refreshes(self, minimum=2):
        with self.condition:
            return self.condition.wait_for(lambda: self.refreshes >= minimum, timeout=1.5)


class FalseyTerminalStream(TerminalStream):
    def __bool__(self):
        return False


class InstallerUITests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="installer-ui-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.environment = {
            "HOME": str(self.home),
            "CODEX_HOME": str(self.home / ".codex"),
            "TERM": "xterm-256color",
            "COLUMNS": "80",
        }
        self.environment_patch = patch.dict(
            os.environ,
            {"HOME": str(self.home), "CODEX_HOME": str(self.home / ".codex")},
        )
        self.environment_patch.start()
        self.addCleanup(self.environment_patch.stop)

    def interface(self, tty=True, environ=None, **kwargs):
        stream = TerminalStream(tty=tty)
        interface = ui_module.InstallerUI(
            stream=stream,
            environ=self.environment if environ is None else environ,
            **kwargs,
        )
        return interface, stream

    def plan(self, changes=None):
        return {
            "client": "codex",
            "codexVersion": "0.163.0",
            "bundledPluginVersion": "0.2.20",
            "source": str(self.home / "managed-marketplace"),
            "stateFile": str(self.home / "setup.json"),
            "traceRoot": str(self.home / "rollout-traces"),
            "persistentLoginSetup": True,
            "commands": [],
            "changes": [] if changes is None else changes,
            "notes": ["Recording may contain private content."],
            "restartRequired": True,
            "nativeVerified": False,
        }

    def assert_no_background_refresh(self, stream):
        settled = stream.getvalue()
        threading.Event().wait(0.3)
        self.assertEqual(stream.getvalue(), settled, "progress kept writing after stage exit")

    def test_json_mode_never_enhances_or_emits_stage_output(self):
        interface, stream = self.interface(json_mode=True)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            with interface.stage("Checking synthetic profile"):
                pass
            interface.summary(self.plan())
            interface.result({"status": "configured", "plan": self.plan()})
        self.assertFalse(interface.enhanced)
        self.assertFalse(interface.animated)
        self.assertEqual(stream.getvalue(), "")
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(list(self.home.iterdir()), [])

    def test_non_tty_dumb_and_ci_leave_stage_output_to_plain_renderer(self):
        cases = [
            (False, self.environment),
            (True, {**self.environment, "TERM": "dumb"}),
            (True, {**self.environment, "CI": "1"}),
        ]
        for tty, environ in cases:
            with self.subTest(tty=tty, environ=environ):
                interface, stream = self.interface(tty=tty, environ=environ)
                self.assertFalse(interface.enhanced)
                self.assertFalse(interface.animated)
                with interface.stage("Inspect synthetic files"):
                    pass
                self.assertEqual(stream.getvalue(), "")

    def test_explicit_stream_is_used_even_when_it_is_falsey(self):
        stream = FalseyTerminalStream()
        interface = ui_module.InstallerUI(
            stream=stream, environ=self.environment, no_animation=True
        )
        self.assertTrue(interface.enhanced)
        with interface.stage("Synthetic check"):
            pass
        self.assertIn("Synthetic check", plain(stream.getvalue()))

    def test_no_color_preserves_enhanced_layout_without_sgr(self):
        for value in ("", "1"):
            with self.subTest(value=value):
                interface, stream = self.interface(environ={**self.environment, "NO_COLOR": value})
                self.assertTrue(interface.enhanced)
                self.assertTrue(interface.animated)
                with interface.stage("Inspect synthetic files"):
                    self.assertTrue(stream.wait_for_refreshes())
                self.assertIn("Inspect synthetic files", stream.getvalue())
                self.assertIsNone(SGR.search(stream.getvalue()))

    def test_motion_switches_keep_static_feedback_without_line_control(self):
        cases = [
            {"no_animation": True},
            {"environ": {**self.environment, "DSH_TRACE_NO_ANIMATION": "1"}},
        ]
        for options in cases:
            with self.subTest(options=options):
                interface, stream = self.interface(**options)
                self.assertTrue(interface.enhanced)
                self.assertFalse(interface.animated)
                with interface.stage("Check synthetic cache"):
                    pass
                output = stream.getvalue()
                self.assertIn("Check synthetic cache", plain(output))
                self.assertNotIn("\r", output)
                self.assertNotIn("\x1b[2K", output)
                self.assert_no_background_refresh(stream)

    def test_animated_success_stops_refreshing_before_return(self):
        interface, stream = self.interface()
        self.assertTrue(interface.animated)
        with interface.stage("Check synthetic cache"):
            self.assertTrue(stream.wait_for_refreshes(), "animated stage never refreshed")
        self.assertIn("Check synthetic cache", plain(stream.getvalue()))
        self.assertTrue(stream.getvalue().endswith("\n"))
        self.assert_no_background_refresh(stream)

    def test_stage_preserves_failure_and_interrupt_and_stops_refreshing(self):
        for failure in (RuntimeError("synthetic failure"), KeyboardInterrupt()):
            with self.subTest(failure=type(failure).__name__):
                interface, stream = self.interface()
                with self.assertRaises(type(failure)) as caught:
                    with interface.stage("Inspect synthetic cache"):
                        self.assertTrue(stream.wait_for_refreshes())
                        raise failure
                self.assertIs(caught.exception, failure)
                output = plain(stream.getvalue())
                final_line = output.splitlines()[-1].lower()
                self.assertIn("inspect synthetic cache", final_line)
                self.assertRegex(
                    final_line, r"fail|cancel|interrupt|stopped|error|\[x\]|\[!\]|✗|×|^x\s"
                )
                self.assert_no_background_refresh(stream)

    def test_narrow_terminal_truncates_each_animated_frame_to_one_line(self):
        for label in ("Checking " + "very-long-synthetic-path/" * 5, "检查 " + "录制目录/" * 20):
            with self.subTest(label=label):
                with patch("shutil.get_terminal_size", return_value=os.terminal_size((24, 24))):
                    interface, stream = self.interface(
                        environ={**self.environment, "COLUMNS": "24"}
                    )
                    with interface.stage(label):
                        self.assertTrue(stream.wait_for_refreshes())
                frames = [line for line in re.split(r"[\r\n]", plain(stream.getvalue())) if line]
                self.assertTrue(frames)
                self.assertTrue(all(columns(frame) <= 24 for frame in frames), frames)
                self.assert_no_background_refresh(stream)

    def test_summary_sanitizes_untrusted_path_controls(self):
        path = "/safe/\x1b[2J\nINJECTED\r\x07\x9b/file"
        interface, stream = self.interface(
            environ={**self.environment, "NO_COLOR": "1"}, no_animation=True
        )
        interface.summary(
            self.plan([{"action": "persist-bundled-plugin", "path": path, "version": "0.2.20"}])
        )
        output = stream.getvalue()
        for control in ("\x1b", "\r", "\x07", "\x9b"):
            self.assertNotIn(control, output)
        injected_lines = [line for line in output.splitlines() if "INJECTED" in line]
        self.assertTrue(injected_lines)
        self.assertTrue(all("/safe/" in line for line in injected_lines))

    def test_summary_keeps_each_changed_path_visible(self):
        changes = [
            {"action": "persist-bundled-plugin", "path": str(self.home / "source")},
            {"action": "create-recording-directory", "path": str(self.home / "recordings")},
            {"action": "write-login-launch-agent", "path": str(self.home / "agent.plist")},
        ]
        interface, stream = self.interface(no_animation=True)
        interface.summary(self.plan(changes))
        output = plain(stream.getvalue())
        for change in changes:
            self.assertIn(change["path"], output)

    def test_repair_summary_distinguishes_python_change_and_missing_files(self):
        outputs = {}
        for reason in ("python-changed", "missing-files"):
            interface, stream = self.interface(no_animation=True)
            change = {
                "action": "repair-owned-installed-files",
                "path": str(self.home / "plugin-cache"),
                "reason": reason,
                "missing": ["server/main.py", "assets/viewer.html"],
                "previousPython": "/synthetic/old-python",
                "pythonExecutable": "/synthetic/new-python",
            }
            interface.summary(self.plan([change]))
            outputs[reason] = plain(stream.getvalue())
            self.assertIn(change["path"], outputs[reason])
        self.assertIn("python", outputs["python-changed"].lower())
        self.assertRegex(outputs["missing-files"].lower(), r"\b2\b.*missing|missing.*\b2\b")
        self.assertNotEqual(outputs["python-changed"], outputs["missing-files"])

    def test_result_distinguishes_unchanged_and_never_claims_recording_verification(self):
        outputs = {}
        for status in ("configured", "unchanged"):
            interface, stream = self.interface(no_animation=True)
            interface.result(
                {
                    "status": status,
                    "pluginVersion": "0.2.20",
                    "plan": self.plan(),
                    "nativeVerified": False,
                    "next": "Reopen Codex and run a new task.",
                }
            )
            outputs[status] = plain(stream.getvalue())
            self.assertIn("0.2.20", outputs[status])
            for line in outputs[status].lower().splitlines():
                if ("recording" in line or "native" in line) and "verified" in line:
                    self.assertRegex(line, r"\bnot\b|\bunverified\b|\byet\b", line)
        self.assertNotEqual(outputs["configured"], outputs["unchanged"])

    def test_non_success_result_does_not_print_installation_success(self):
        for status in ("error", "needs-setup", "configured-needs-native-check"):
            with self.subTest(status=status):
                interface, stream = self.interface(no_animation=True)
                handled = interface.result({"status": status})
                self.assertFalse(handled)
                self.assertEqual(stream.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
