"""Exercise confirmation against a real independent controlling terminal."""

import errno
import os
import re
import select
import signal
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

if os.name == "posix":
    import fcntl
    import pty
    import termios


CHILD = r"""
import importlib.util, json, os, sys
from types import SimpleNamespace
spec = importlib.util.spec_from_file_location("confirmation_fixture", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
installer = module.Installer.__new__(module.Installer)
flags = set(sys.argv[4:])
installer.args = SimpleNamespace(
    yes=sys.argv[2] == "yes", action="setup", verbose="verbose" in flags,
    json="json" in flags, no_animation=True,
)
environment = dict(os.environ)
if "plain" in flags:
    environment["TERM"] = "dumb"
installer.ui = module.terminal_ui().InstallerUI(
    environ=environment, json_mode=installer.args.json,
    no_animation=True, verbose=installer.args.verbose,
)
if "guard-open" in flags:
    import builtins
    def unexpected_open(*args, **kwargs):
        raise AssertionError("confirmation unexpectedly opened a terminal")
    builtins.open = unexpected_open
print("TTY_STATE:" + json.dumps({"stdin": os.isatty(0), "stdout": os.isatty(1)}), flush=True)
if "alignment" in flags:
    print(installer.ui.progress_line("[o_o] ✓", "STEP_TEXT"), file=sys.stderr, flush=True)
    installer.ui.notice("NOTICE_TEXT")
try:
    installer.confirm({
        "notes": ["SYNTHETIC_TERMINAL_TEST_ONLY"],
        "stateFile": "/synthetic/setup.json",
        "source": "/synthetic/plugin",
        "traceRoot": "/synthetic/recordings",
        "customTraceRoot": False,
        "persistentLoginSetup": True,
        "bundledPluginVersion": "0.2.20",
        "commands": [[
            "/synthetic/codex", "plugin", "marketplace", "add", "/synthetic/plugin", "--json",
        ]],
        "changes": [{"action": "persist-bundled-plugin", "path": "/synthetic/plugin"}],
    })
except module.SetupError as exc:
    print("SETUP_ERROR:" + str(exc), flush=True)
    if sys.argv[3] == "read-pipe":
        print("UNCONSUMED:" + sys.stdin.read(), flush=True)
    raise SystemExit(3)
print("CONFIRMED", flush=True)
if "alignment" in flags:
    installer.ui.result({
        "status": "configured", "plan": {"traceRoot": "/synthetic/recordings"},
        "pluginVersion": "fixture",
    })
"""


@unittest.skipUnless(os.name == "posix" and hasattr(os, "fork"), "controlling PTY needs POSIX")
class InstallerTerminalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="installer-terminal-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.script = Path(__file__).resolve().parents[1] / "scripts/setup.py"
        self.environment = {
            **os.environ,
            "HOME": str(self.root),
            "CODEX_HOME": str(self.root / ".codex"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPYCACHEPREFIX": str(self.root / "python-cache"),
            "TERM": "xterm-256color",
        }
        self.environment.pop("CI", None)

    def controlling_terminal(self, answer, flags=()):
        answers = [answer] if isinstance(answer, str) else list(answer)
        pid, master = pty.fork()
        if pid == 0:
            fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
            os.chdir(self.root)
            os.execve(
                sys.executable,
                [sys.executable, "-B", "-c", CHILD, str(self.script), "no", "no-read", *flags],
                self.environment,
            )
        output = bytearray()
        status = None
        sent = 0
        deadline = time.monotonic() + 5
        try:
            while True:
                if time.monotonic() >= deadline:
                    self.fail("confirmation timed out in independent PTY")
                ready, _, _ = select.select([master], [], [], 0.1)
                if ready:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError as exc:
                        if exc.errno != errno.EIO:
                            raise
                        chunk = b""
                    if not chunk:
                        break
                    output.extend(chunk)
                    self.assertLess(len(output), 65536)
                    prompts = output.count(b"Apply setup? [y/N/d=details] ") + output.count(
                        b"Apply this dsh-trace-extension setup? [y/N] "
                    )
                    while prompts > sent and sent < len(answers):
                        os.write(master, answers[sent].encode())
                        sent += 1
                if status is None:
                    done, value = os.waitpid(pid, os.WNOHANG)
                    if done:
                        status = value
            if status is None:
                _, status = os.waitpid(pid, 0)
        finally:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
            os.close(master)
        return os.waitstatus_to_exitcode(status), output.decode(errors="replace"), sent

    def test_controlling_terminal_accepts_yes(self):
        code, output, prompted = self.controlling_terminal("yes\n")
        self.assertEqual(code, 0, output)
        self.assertTrue(prompted)
        self.assertIn('"stdin": true', output)
        self.assertIn("CONFIRMED", output)
        self.assertNotIn("Refresh Codex Trace", output)
        self.assertNotIn("Local recording", output)
        self.assertNotIn("/synthetic/plugin", output)
        self.assertRegex(output, r"\[\?_\?\]\s+Apply setup\? \[y/N/d=details\] ")

    def test_real_terminal_aligns_steps_prompt_completion_and_next_action(self):
        code, output, _ = self.controlling_terminal("yes\n", flags=("alignment",))
        self.assertEqual(code, 0, output)
        text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", output)
        positions = []
        for label in (
            "STEP_TEXT",
            "NOTICE_TEXT",
            "Apply setup?",
            "Local setup complete",
            "Fully quit",
        ):
            matches = [line for line in text.splitlines() if label in line]
            self.assertEqual(len(matches), 1, text)
            line = matches[0]
            positions.append(line.index(label))
        self.assertEqual(len(set(positions)), 1, text)

    def test_controlling_terminal_default_and_explicit_no_cancel(self):
        for answer in ("\n", "no\n"):
            with self.subTest(answer=answer):
                code, output, prompted = self.controlling_terminal(answer)
                self.assertEqual(code, 3, output)
                self.assertTrue(prompted, output)
                self.assertIn("Setup cancelled; no changes applied.", output)
                self.assertNotIn("No interactive terminal", output)

    def test_details_then_yes_is_the_only_authorization(self):
        code, output, sent = self.controlling_terminal(["d\n", "yes\n"])
        self.assertEqual(code, 0, output)
        self.assertEqual(sent, 2)
        self.assertIn("CONFIRMED", output)
        self.assertEqual(output.count("Apply setup? [y/N/d=details] "), 2)
        self.assertIn("/synthetic/setup.json", output)
        self.assertIn("/synthetic/codex plugin marketplace add /synthetic/plugin --json", output)

    def test_details_then_default_or_eof_still_cancels(self):
        for answer in ("\n", "\x04"):
            with self.subTest(answer=repr(answer)):
                code, output, sent = self.controlling_terminal(["d\n", answer])
                self.assertEqual(code, 3, output)
                self.assertEqual(sent, 2)
                self.assertIn("/synthetic/setup.json", output)
                self.assertIn("Setup cancelled; no changes applied.", output)
                self.assertNotIn("CONFIRMED", output)

    def test_repeated_details_are_printed_once_and_never_apply(self):
        code, output, sent = self.controlling_terminal(["d\n", "d\n", "y\n"])
        self.assertEqual(code, 0, output)
        self.assertEqual(sent, 3)
        self.assertEqual(output.count("Apply setup? [y/N/d=details] "), 3)
        self.assertEqual(output.count("/synthetic/setup.json"), 1)
        self.assertIn("CONFIRMED", output)

    def test_eof_at_initial_prompt_cancels(self):
        code, output, sent = self.controlling_terminal("\x04")
        self.assertEqual(code, 3, output)
        self.assertEqual(sent, 1)
        self.assertIn("Setup cancelled; no changes applied.", output)
        self.assertNotIn("CONFIRMED", output)

    def test_verbose_already_shows_details_once(self):
        code, output, sent = self.controlling_terminal(["d\n", "y\n"], flags=("verbose",))
        self.assertEqual(code, 0, output)
        self.assertEqual(sent, 2)
        self.assertEqual(output.count("/synthetic/setup.json"), 1)

    def test_plain_and_json_modes_keep_original_prompt_and_complete_plan(self):
        for flag in ("plain", "json"):
            with self.subTest(flag=flag):
                code, output, sent = self.controlling_terminal("y\n", flags=(flag,))
                self.assertEqual(code, 0, output)
                self.assertEqual(sent, 1)
                self.assertIn("Apply this dsh-trace-extension setup? [y/N] ", output)
                self.assertNotIn("d=details", output)
                self.assertIn("/synthetic/setup.json", output)
                self.assertIn("/synthetic/plugin", output)
                self.assertNotIn("\x1b[", output)

    def test_no_controlling_terminal_preserves_piped_stdin(self):
        result = subprocess.run(
            [sys.executable, "-B", "-c", CHILD, str(self.script), "no", "read-pipe"],
            cwd=self.root,
            env=self.environment,
            input="yes\n",
            capture_output=True,
            text=True,
            start_new_session=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("No interactive terminal", result.stdout)
        self.assertIn("UNCONSUMED:yes", result.stdout)

    def test_yes_does_not_require_a_controlling_terminal(self):
        result = subprocess.run(
            [sys.executable, "-B", "-c", CHILD, str(self.script), "yes", "no-read"],
            cwd=self.root,
            env=self.environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            start_new_session=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CONFIRMED", result.stdout)
        self.assertNotIn("Apply this", result.stderr)

    def test_yes_verbose_never_opens_a_terminal(self):
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                CHILD,
                str(self.script),
                "yes",
                "no-read",
                "verbose",
                "guard-open",
            ],
            cwd=self.root,
            env=self.environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            start_new_session=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CONFIRMED", result.stdout)
        self.assertIn("/synthetic/setup.json", result.stderr)
        self.assertNotIn("Apply setup?", result.stderr)
        self.assertNotIn("Apply this", result.stderr)
