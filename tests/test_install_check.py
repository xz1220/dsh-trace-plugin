"""Installation checks accept ordinary empty and unfinished recordings."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fixtures import Fixture

ROOT = Path(__file__).resolve().parents[1]


class InstallCheckTests(unittest.TestCase):
    def test_files_and_protocol_can_be_checked_without_a_recording(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = self.verify(Path(temporary))
        self.assertTrue(report["installedFilesMatchSource"])
        self.assertTrue(report["versionedResourceAndLegacyAlias"])
        self.assertIn("server/_version.py", report["checkedInstalledFiles"])
        self.assertIn("server/snapshots.py", report["checkedInstalledFiles"])
        self.assertNotIn("recording", report)

    def test_empty_recording_does_not_require_a_model_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            Fixture(root / "recordings" / "empty")
            report = self.verify(root, "--trace-id", "trace-test")
        self.assertEqual(report["recording"]["requests"], 0)

    def test_running_request_without_usage_or_previous_context_remains_inspectable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = Fixture(root / "recordings" / "running")
            request = fixture.payload(
                {
                    "previous_response_id": "missing-response",
                    "input": [
                        {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "KNOWN_INCREMENT"}],
                        }
                    ],
                },
                "inference_request",
            )
            fixture.append(
                "inference_started", inference_call_id="running", request_payload=request
            )
            report = self.verify(
                root, "--trace-id", "trace-test", "--expect-text", "KNOWN_INCREMENT"
            )
        self.assertEqual(report["recording"]["requests"], 1)
        self.assertEqual(report["recording"]["expectedTextChecks"], 1)

    @staticmethod
    def verify(root, *arguments):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/verify-install.py"),
                "--plugin-dir",
                str(ROOT / "plugins/codex-dsh-trace"),
                *arguments,
            ],
            env={
                **os.environ,
                "CODEX_HOME": str(root / "home"),
                "CODEX_ROLLOUT_TRACE_ROOT": str(root / "recordings"),
            },
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
        return json.loads(result.stdout)


if __name__ == "__main__":
    unittest.main()
