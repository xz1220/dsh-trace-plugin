"""Exercise bootstrap boundaries with isolated files and a fake GitHub transport."""

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "install.sh"
COMMIT = "a" * 40


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="trace-bootstrap-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.downloads = self.root / "downloads"
        self.downloads.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        self.log = self.root / "helper-argv.json"
        self.calls = self.root / "github-calls.jsonl"
        self.env = {
            **os.environ,
            "HOME": str(self.home),
            "TMPDIR": str(self.downloads),
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "DSH_TRACE_PYTHON": sys.executable,
            "DSH_TRACE_REF": "main",
            "DSH_TRACE_REPOSITORY": "example/trace",
            "BOOTSTRAP_TEST_LOG": str(self.log),
            "BOOTSTRAP_TEST_CALLS": str(self.calls),
        }
        self.helper = (
            "import json,os,sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['BOOTSTRAP_TEST_LOG']).write_text(json.dumps(sys.argv[1:]))\n"
            "print('helper ran')\n"
        ).encode()

    def executable(self, name, source):
        target = self.bin / name
        target.write_text(source)
        target.chmod(0o700)
        return target

    def github(self, corrupt=False, denied=False):
        data = base64.b64encode(self.helper).decode()
        sha = hashlib.sha1(b"blob " + str(len(self.helper)).encode() + b"\0" + self.helper)
        response = {
            "type": "file",
            "path": "scripts/setup.py",
            "encoding": "base64",
            "content": data,
            "sha": "bad" if corrupt else sha.hexdigest(),
        }
        source = (
            f"#!{sys.executable}\n"
            "import json,os,sys\n"
            "from pathlib import Path\n"
            "with Path(os.environ['BOOTSTRAP_TEST_CALLS']).open('a') as stream:\n"
            "    stream.write(json.dumps(sys.argv[1:])+'\\n')\n"
        )
        if denied:
            source += "raise SystemExit(1)\n"
        else:
            source += (
                "endpoint=sys.argv[2]\n"
                f"print(json.dumps({{'sha': '{COMMIT}'}}) if '/commits/' in endpoint "
                f"else {json.dumps(json.dumps(response))})\n"
            )
        self.executable("gh", source)
        # A denied fake source must never fall through to the real network.
        self.executable("curl", "#!/bin/sh\nexit 22\n")

    def pipe(self, *arguments, source=None, cwd=None):
        return subprocess.run(
            ["sh", "-s", "--", *arguments],
            input=BOOTSTRAP.read_text() if source is None else source,
            text=True,
            capture_output=True,
            env=self.env,
            cwd=cwd or self.root,
            timeout=15,
        )

    def test_help_needs_no_runtime_or_network(self):
        self.env["DSH_TRACE_PYTHON"] = "missing-python"
        result = self.pipe("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("doctor", result.stdout)
        self.assertFalse(self.log.exists())
        self.assertFalse(self.calls.exists())

    def test_local_checkout_preserves_arguments_and_spaced_paths(self):
        checkout = self.root / "checkout with spaces"
        (checkout / "scripts").mkdir(parents=True)
        (checkout / ".agents/plugins").mkdir(parents=True)
        (checkout / ".agents/plugins/marketplace.json").write_text("{}")
        (checkout / "scripts/setup.py").write_bytes(self.helper)
        shutil.copyfile(BOOTSTRAP, checkout / "install.sh")
        trace = str(self.root / "trace data")
        result = subprocess.run(
            ["sh", str(checkout / "install.sh"), "doctor", "--trace-root", trace, "--json"],
            capture_output=True,
            text=True,
            env=self.env,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        args = json.loads(self.log.read_text())
        self.assertEqual(args[:4], ["doctor", "--trace-root", trace, "--json"])
        self.assertEqual(args[-2:], ["--source", str(checkout.resolve())])
        self.assertFalse(self.calls.exists())

    def test_remote_helper_is_blob_verified_and_pinned(self):
        self.github()
        self.env["GH_HOST"] = "enterprise.invalid"
        result = self.pipe("--dry-run", "--ref", "release/test")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = json.loads(self.log.read_text())
        self.assertEqual(args[-4:], ["--source", "example/trace", "--ref", COMMIT])
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertEqual(calls[0][1], "repos/example/trace/commits/release%2Ftest")
        self.assertTrue(calls[1][1].endswith("?ref=" + COMMIT))
        self.assertTrue(all(call[-2:] == ["--hostname", "github.com"] for call in calls))
        self.assertEqual(list(self.downloads.iterdir()), [])

    def test_piped_bootstrap_ignores_current_directory_helper(self):
        (self.root / "scripts").mkdir()
        (self.root / ".agents/plugins").mkdir(parents=True)
        (self.root / ".agents/plugins/marketplace.json").write_text("{}")
        (self.root / "scripts/setup.py").write_text("raise SystemExit('untrusted cwd helper')")
        self.github()
        result = self.pipe("--dry-run", cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("helper ran", result.stdout)
        self.assertTrue(self.calls.exists())

    def test_fork_source_resolves_and_downloads_from_that_fork(self):
        self.github()
        result = self.pipe("--dry-run", "--source", "other/fork", "--ref", "fork-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = json.loads(self.log.read_text())
        self.assertEqual(args[-4:], ["--source", "other/fork", "--ref", COMMIT])
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertEqual(calls[0][1], "repos/other/fork/commits/fork-only")
        self.assertTrue(calls[1][1].startswith("repos/other/fork/contents/"))

    def test_corrupt_helper_is_not_run_and_temporary_data_is_removed(self):
        self.github(corrupt=True)
        result = self.pipe("--yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("failed validation", result.stderr)
        self.assertFalse(self.log.exists())
        self.assertEqual(list(self.downloads.iterdir()), [])

    def test_private_source_failure_explains_authentication(self):
        self.github(denied=True)
        result = self.pipe("--yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Private repositories require gh auth login", result.stderr)
        self.assertFalse(self.log.exists())
        self.assertEqual(list(self.downloads.iterdir()), [])

    def test_explicit_incompatible_python_is_not_silently_replaced(self):
        stub = self.executable("old-python", "#!/bin/sh\nexit 1\n")
        self.env["DSH_TRACE_PYTHON"] = str(stub)
        result = self.pipe("--dry-run")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be Python 3.9", result.stderr)
        self.assertFalse(self.calls.exists())

    def test_truncated_downloads_do_not_run_commands_or_dump_environment(self):
        self.github()
        source = BOOTSTRAP.read_text()
        positions = [
            source.index("set -eu") + len("set"),
            source.index("dsh_python=", source.index("dsh_usage()")),
            source.index("dsh_get_json()"),
            len(source.rstrip()) - 1,
        ]
        for length in positions:
            with self.subTest(length=length):
                result = self.pipe("--yes", source=source[:length])
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("BOOTSTRAP_TEST_LOG", result.stdout)
                self.assertFalse(self.log.exists())
                self.assertFalse(self.calls.exists())


if __name__ == "__main__":
    unittest.main()
