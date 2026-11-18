"""Exercise confirmation against a real independent controlling terminal."""

import errno
import os
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

if os.name == "posix":
    import pty


CHILD = r"""
import importlib.util, json, os, sys
from types import SimpleNamespace
spec = importlib.util.spec_from_file_location("confirmation_fixture", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
installer = module.Installer.__new__(module.Installer)
installer.args = SimpleNamespace(yes=sys.argv[2] == "yes")
print("TTY_STATE:" + json.dumps({"stdin": os.isatty(0), "stdout": os.isatty(1)}), flush=True)
try:
    installer.confirm({"notes": ["SYNTHETIC_TERMINAL_TEST_ONLY"]})
except module.SetupError as exc:
    print("SETUP_ERROR:" + str(exc), flush=True)
    if sys.argv[3] == "read-pipe":
        print("UNCONSUMED:" + sys.stdin.read(), flush=True)
    raise SystemExit(3)
print("CONFIRMED", flush=True)
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
        }

    def controlling_terminal(self, answer):
        pid, master = pty.fork()
        if pid == 0:
            os.chdir(self.root)
            os.execve(
                sys.executable,
                [sys.executable, "-B", "-c", CHILD, str(self.script), "no", "no-read"],
                self.environment,
            )
        output = bytearray()
        status = None
        sent = False
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
                    if b"Apply this dsh-trace-extension setup? [y/N] " in output and not sent:
                        os.write(master, answer.encode())
                        sent = True
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

    def test_controlling_terminal_default_and_explicit_no_cancel(self):
        for answer in ("\n", "no\n"):
            with self.subTest(answer=answer):
                code, output, prompted = self.controlling_terminal(answer)
                self.assertEqual(code, 3, output)
                self.assertTrue(prompted, output)
                self.assertIn("Setup cancelled; no changes applied.", output)
                self.assertNotIn("No interactive terminal", output)

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
