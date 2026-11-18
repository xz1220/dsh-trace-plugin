"""Check terminal presentation without touching a real Codex profile."""

import contextlib
import importlib.util
import io
import os
import re
import shlex
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
            "customTraceRoot": False,
            "recordingDirectoryChanged": False,
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
        interface, stream = self.interface(json_mode=True, verbose=True)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            interface.header("0.2.20")
            with interface.stage("Checking synthetic profile"):
                pass
            interface.summary(self.plan())
            interface.result({"status": "configured", "plan": self.plan()})
            interface.notice("Synthetic warning")
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

    def test_animation_status_and_message_bodies_share_a_terminal_column(self):
        for no_color in (False, True):
            environment = {**self.environment, **({"NO_COLOR": "1"} if no_color else {})}
            interface, stream = self.interface(environ=environment)
            label = "Aligned body"
            markers = [*interface.frames, "[o_o] ✓", "[!_!] ×", "[o_o]"]
            rows = [plain(interface.progress_line(marker, label)) for marker in markers]
            for face in ("[o_o]", "[?_?]", "[^_^]", "[>_>]", "[!_!]"):
                interface.notice(label, face=face)
            rows.extend(plain(stream.getvalue()).splitlines())
            positions = {columns(row[: row.index(label)]) for row in rows}
            self.assertEqual(len(positions), 1, rows)
            self.assertNotIn("\x1b", interface.prefix("[?_?]"))

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
                self.assertEqual(len(plain(output).splitlines()), 1)
                self.assertNotIn("\r", output)
                self.assertNotIn("\x1b[2K", output)
                self.assert_no_background_refresh(stream)

    def test_static_stage_still_reports_failure_and_preserves_the_exception(self):
        interface, stream = self.interface(no_animation=True)
        failure = RuntimeError("synthetic failure")
        with self.assertRaises(RuntimeError) as caught:
            with interface.stage("Inspect synthetic cache"):
                raise failure
        self.assertIs(caught.exception, failure)
        output = plain(stream.getvalue())
        self.assertEqual(len(output.splitlines()), 2)
        self.assertIn("stopped", output.splitlines()[-1].lower())
        self.assertNotIn("\r", output)

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
            self.plan([{"action": "persist-bundled-plugin", "path": path, "version": "0.2.20"}]),
            details=True,
        )
        output = stream.getvalue()
        for control in ("\x1b", "\r", "\x07", "\x9b"):
            self.assertNotIn(control, output)
        injected_lines = [line for line in output.splitlines() if "INJECTED" in line]
        self.assertTrue(injected_lines)
        self.assertTrue(all("/safe/" in line for line in injected_lines))

    def test_details_keep_each_changed_path_visible(self):
        changes = [
            {"action": "persist-bundled-plugin", "path": str(self.home / "source")},
            {"action": "create-recording-directory", "path": str(self.home / "recordings")},
            {"action": "write-login-launch-agent", "path": str(self.home / "agent.plist")},
        ]
        interface, stream = self.interface(no_animation=True)
        interface.summary(self.plan(changes), details=True)
        output = plain(stream.getvalue())
        for change in changes:
            self.assertIn(change["path"], output)

    def test_unchanged_still_guides_a_user_who_has_not_reopened_codex(self):
        interface, stream = self.interface(no_animation=True)
        interface.result({"status": "unchanged", "plan": self.plan(), "pluginVersion": "0.2.20"})
        output = plain(stream.getvalue()).lower()
        self.assertIn("if you haven't reopened", output)
        self.assertIn("fully quit and reopen", output)

    def test_details_preserve_python_change_and_missing_file_repair_reasons(self):
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
            interface.summary(self.plan([change]), details=True)
            outputs[reason] = plain(stream.getvalue())
            self.assertIn(change["path"], outputs[reason])
            if reason == "python-changed":
                self.assertIn(change["previousPython"], outputs[reason])
                self.assertIn(change["pythonExecutable"], outputs[reason])
        self.assertIn("python", outputs["python-changed"].lower())
        self.assertRegex(outputs["missing-files"].lower(), r"\b2\b.*missing|missing.*\b2\b")
        self.assertNotEqual(outputs["python-changed"], outputs["missing-files"])

    def test_compact_recording_change_hides_technical_paths(self):
        changes = [
            {"action": "persist-bundled-plugin", "path": str(self.home / "source")},
            {"action": "write-login-launch-agent", "path": str(self.home / "agent.plist")},
            {"action": "set-login-environment", "value": str(self.home / "rollout-traces")},
        ]
        plan = self.plan(changes)
        plan["commands"] = [
            ["/synthetic/codex", "plugin", "marketplace", "add", plan["source"], "--json"]
        ]
        interface, stream = self.interface(no_animation=True)
        interface.summary(plan)
        output = plain(stream.getvalue())
        for hidden in (
            plan["source"],
            plan["stateFile"],
            plan["traceRoot"],
            changes[0]["path"],
            changes[1]["path"],
            "/synthetic/codex",
        ):
            self.assertNotIn(hidden, output)
        self.assertIn("record", output.lower())
        self.assertIn("login", output.lower())
        self.assertRegex(output.lower(), r"private|credentials|prompts|sensitive")

    def test_pure_persist_or_repair_has_no_standing_summary(self):
        for reason in (None, "python-changed", "missing-files"):
            with self.subTest(reason=reason):
                changes = [{"action": "persist-bundled-plugin", "path": "/synthetic/source"}]
                if reason:
                    changes.append(
                        {
                            "action": "repair-owned-installed-files",
                            "path": "/synthetic/cache",
                            "reason": reason,
                            "missing": ["server/main.py"],
                            "previousPython": "/synthetic/old-python",
                            "pythonExecutable": "/synthetic/new-python",
                        }
                    )
                interface, stream = self.interface(no_animation=True)
                interface.summary(self.plan(changes))
                self.assertEqual(stream.getvalue(), "")

    def test_only_actual_recording_changes_emit_one_compact_impact_notice(self):
        actions = (
            "set-login-environment",
            "create-recording-directory",
            "write-login-launch-agent",
            "remove-owned-launch-agent",
        )
        for action in actions:
            with self.subTest(action=action):
                plan = self.plan([{"action": action, "path": "/synthetic/settings"}])
                plan["persistentLoginSetup"] = action != "remove-owned-launch-agent"
                interface, stream = self.interface(no_animation=True)
                interface.summary(plan)
                output = plain(stream.getvalue())
                self.assertEqual(len([line for line in output.splitlines() if line.strip()]), 1)
                self.assertIn("record", output.lower())
                if action == "remove-owned-launch-agent":
                    self.assertRegex(output.lower(), r"this login|current login")
                    self.assertNotRegex(
                        output.lower(), r"recording (?:has )?stopped|stop recording"
                    )
                else:
                    self.assertRegex(output.lower(), r"private|credentials|prompts|sensitive")

    def test_default_header_is_silent_to_keep_only_steps_visible(self):
        interface, stream = self.interface(no_animation=True)
        interface.header("0.2.20")
        self.assertEqual(stream.getvalue(), "")

    def test_verbose_header_is_one_robot_line(self):
        interface, stream = self.interface(no_animation=True, verbose=True)
        interface.header("0.2.20")
        output = plain(stream.getvalue())
        self.assertEqual(len(output.splitlines()), 1)
        self.assertRegex(output, r"^\s*\[[^\]\s]{3}\]\s")

    def test_all_enhanced_sections_are_robot_prefixed_without_blank_spacers(self):
        interface, stream = self.interface(no_animation=True)
        plan = self.plan([{"action": "write-login-launch-agent", "path": "/synthetic/agent"}])
        interface.header("0.2.20")
        interface.summary(plan)
        interface.summary(plan, details=True)
        interface.result(
            {
                "status": "configured",
                "plan": plan,
                "pluginVersion": "0.2.20",
                "warnings": ["Check synthetic recovery."],
            }
        )
        interface.notice("Synthetic error", face="[!_!]", code="31")
        output = plain(stream.getvalue())
        self.assertNotIn("\n\n", output)
        self.assertTrue(output.splitlines())
        for line in output.splitlines():
            self.assertTrue(line.strip(), repr(output))
            self.assertRegex(line, r"^\s*\[[^\]\s]{3}\]\s", line)

    def test_notice_sanitizes_text_and_uses_the_requested_face(self):
        interface, stream = self.interface(
            environ={**self.environment, "NO_COLOR": "1"}, no_animation=True
        )
        interface.notice("Synthetic\nerror\x1b[2J\x07", face="[!_!]", code="31")
        output = stream.getvalue()
        self.assertEqual(len(output.splitlines()), 1)
        self.assertRegex(output, r"^\s*\[!_!\]\s")
        self.assertNotIn("\x1b", output)
        self.assertNotIn("\x07", output)

    def test_verbose_plan_and_explicit_details_show_complete_commands(self):
        plan = self.plan([{"action": "persist-bundled-plugin", "path": str(self.home / "source")}])
        command = [
            "/synthetic/codex",
            "plugin",
            "marketplace",
            "add",
            "source with spaces",
            "--json",
        ]
        plan["commands"] = [command]
        for options, details in (({"verbose": True}, None), ({}, True)):
            with self.subTest(options=options, details=details):
                interface, stream = self.interface(no_animation=True, **options)
                interface.summary(plan, details=details)
                output = plain(stream.getvalue())
                self.assertIn(plan["stateFile"], output)
                self.assertIn(plan["changes"][0]["path"], output)
                self.assertIn(shlex.join(command), output)

    def test_details_keep_both_recording_persistence_modes_visible(self):
        for persistent in (False, True):
            with self.subTest(persistent=persistent):
                plan = self.plan()
                plan["persistentLoginSetup"] = persistent
                interface, stream = self.interface(no_animation=True, verbose=True)
                interface.summary(plan)
                output = plain(stream.getvalue()).lower()
                if persistent:
                    self.assertRegex(output, r"prepare.*login|login.*prepare|login.*enabled")
                else:
                    self.assertRegex(output, r"this login|current login")

    def test_details_false_overrides_verbose_default(self):
        plan = self.plan([{"action": "persist-bundled-plugin", "path": str(self.home / "source")}])
        interface, stream = self.interface(no_animation=True, verbose=True)
        interface.summary(plan, details=False)
        output = plain(stream.getvalue())
        self.assertNotIn(plan["changes"][0]["path"], output)
        self.assertNotIn(plan["stateFile"], output)

    def test_custom_trace_root_remains_visible_in_compact_plan(self):
        plan = self.plan()
        plan["customTraceRoot"] = True
        plan["traceRoot"] = str(self.home / "custom-recordings")
        interface, stream = self.interface(no_animation=True)
        interface.summary(plan)
        self.assertIn(plan["traceRoot"], plain(stream.getvalue()))

    def test_switching_back_to_default_recording_directory_is_not_hidden(self):
        plan = self.plan()
        plan["recordingDirectoryChanged"] = True
        self.assertFalse(plan["customTraceRoot"])
        interface, stream = self.interface(no_animation=True)
        interface.summary(plan)
        self.assertIn(plan["traceRoot"], plain(stream.getvalue()))

    def test_unknown_action_and_command_are_never_collapsed_away(self):
        change = {"action": "future_custom_action", "path": str(self.home / "foreign-target")}
        command = ["/synthetic/codex", "configuration", "reset", "--profile", "synthetic profile"]
        plan = self.plan([change])
        plan["commands"] = [command]
        interface, stream = self.interface(no_animation=True)
        interface.summary(plan)
        output = plain(stream.getvalue())
        self.assertIn(change["action"], output)
        self.assertIn(change["path"], output)
        self.assertIn(shlex.join(command), output)

    def test_other_plugin_ids_sources_and_extra_flags_are_not_treated_as_known(self):
        commands = [
            ["/synthetic/codex", "plugin", "add", "unexpected-plugin@local", "--json"],
            ["/synthetic/codex", "plugin", "marketplace", "add", "/unexpected-source", "--json"],
            ["/synthetic/other", "plugin", "add", "codex-dsh-trace@rollout-local", "--json"],
            [
                "/synthetic/codex",
                "plugin",
                "add",
                "codex-dsh-trace@rollout-local",
                "--json",
                "--force",
            ],
        ]
        for command in commands:
            with self.subTest(command=command):
                interface, stream = self.interface(no_animation=True)
                plan = self.plan()
                plan["commands"] = [command]
                interface.summary(plan)
                self.assertIn(shlex.join(command), plain(stream.getvalue()))

    def test_detailed_commands_are_sanitized(self):
        interface, stream = self.interface(
            environ={**self.environment, "NO_COLOR": "1"}, no_animation=True
        )
        plan = self.plan()
        plan["commands"] = [["/synthetic/codex", "plugin", "add", "bad\x1b[2J\nINJECTED\x07"]]
        interface.summary(plan, details=True)
        output = stream.getvalue()
        for control in ("\x1b", "\x07", "\r"):
            self.assertNotIn(control, output)
        self.assertNotIn("\nINJECTED", output)

    def test_compact_result_hides_technical_details_but_keeps_next_step(self):
        result = {"status": "configured", "plan": self.plan(), "pluginVersion": "0.2.20"}
        for verbose in (False, True):
            with self.subTest(verbose=verbose):
                interface, stream = self.interface(no_animation=True, verbose=verbose)
                interface.result(result)
                output = plain(stream.getvalue())
                self.assertIn("0.2.20", output)
                self.assertIn("reopen", output.lower())
                self.assertIn("new task", output.lower())
                if verbose:
                    self.assertIn(result["plan"]["traceRoot"], output)
                else:
                    self.assertNotIn(result["plan"]["traceRoot"], output)

    def test_expanding_details_also_expands_the_result(self):
        interface, stream = self.interface(no_animation=True)
        plan = self.plan()
        interface.summary(plan, details=True)
        stream.seek(0)
        stream.truncate(0)
        interface.result({"status": "configured", "plan": plan, "pluginVersion": "0.2.20"})
        self.assertIn(plan["traceRoot"], plain(stream.getvalue()))

    def test_compact_result_does_not_hide_warnings(self):
        interface, stream = self.interface(no_animation=True)
        warning = "Preserve the synthetic recovery record before retrying."
        interface.result(
            {
                "status": "configured",
                "plan": self.plan(),
                "pluginVersion": "0.2.20",
                "warnings": [warning],
            }
        )
        self.assertIn(warning, plain(stream.getvalue()))

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
