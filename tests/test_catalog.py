"""Malformed neighboring bundles must not make readable recordings disappear."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/codex-dsh-trace/server"))

from fixtures import Fixture
from store import Catalog, TraceError


class CatalogTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        isolated = patch.dict(os.environ, {"CODEX_ROLLOUT_TRACE_ROOT": str(self.root / "none")})
        isolated.start()
        self.addCleanup(isolated.stop)
        self.good = Fixture(self.root / "recordings" / "good")
        self.bad = Fixture(self.root / "recordings" / "bad")
        self.bad_manifest = self.bad.root / "manifest.json"
        self.manifest = json.loads(self.bad_manifest.read_text())
        self.manifest["trace_id"] = "bad-recording"
        self.catalog = Catalog(self.root / "config.json")
        self.catalog.default_root = self.root / "none"
        self.catalog.register(str(self.root / "recordings"))

    def write_manifest(self, value):
        self.bad_manifest.write_text(json.dumps(value))

    def assert_good_recording_remains(self, error_code):
        self.assertEqual([item["id"] for item in self.catalog.list(force=True)], ["trace-test"])
        self.assertEqual(len(self.catalog.issues), 1)
        issue = self.catalog.issues[0]
        self.assertEqual(issue["errorCode"], error_code)
        return issue

    def test_non_object_manifests_are_reported_without_interrupting_discovery(self):
        for value in ([], None, False, "manifest"):
            with self.subTest(value=value):
                self.write_manifest(value)
                self.assert_good_recording_remains("invalid_recording_manifest")

    def test_invalid_timestamps_do_not_break_sorting_and_keep_known_identity(self):
        for value in ([], {}, "yesterday", True, -1, 1.5):
            with self.subTest(value=value):
                self.write_manifest({**self.manifest, "started_at_unix_ms": value})
                issue = self.assert_good_recording_remains("invalid_recording_manifest")
                self.assertEqual(issue["traceId"], "bad-recording")
                self.assertEqual(issue["threadId"], "thread-root")

    def test_invalid_identifier_keeps_the_other_valid_identifier_for_diagnostics(self):
        self.write_manifest({**self.manifest, "trace_id": []})
        issue = self.assert_good_recording_remains("invalid_identifier")
        self.assertEqual(issue["threadId"], "thread-root")
        self.assertNotIn("traceId", issue)

    def test_unsupported_schema_preserves_identity_alongside_readable_recording(self):
        self.write_manifest({**self.manifest, "schema_version": 99})
        issue = self.assert_good_recording_remains("unsupported_schema")
        self.assertEqual(issue["traceId"], "bad-recording")
        self.assertEqual(issue["threadId"], "thread-root")
        self.assertEqual(issue["schemaVersion"], 99)
        self.assertEqual(issue["errorParams"], {"version": 99})

    def test_layout_errors_keep_identity_for_current_chat_diagnostics(self):
        self.write_manifest({**self.manifest, "raw_event_log": ["trace.jsonl"]})
        issue = self.assert_good_recording_remains("unsupported_recording_layout")
        self.assertEqual(issue["threadId"], "thread-root")

    def test_missing_start_time_remains_supported(self):
        self.manifest.pop("started_at_unix_ms")
        self.write_manifest(self.manifest)
        self.assertEqual(len(self.catalog.list(force=True)), 2)
        self.assertEqual(self.catalog.issues, [])

    def test_malformed_config_fields_return_a_stable_error(self):
        for value in (
            {"roots": None},
            {"roots": "directory"},
            {"roots": [None]},
            {"roots": [""]},
            {"labels": []},
            {"labels": {"trace-test": []}},
        ):
            with self.subTest(value=value):
                self.catalog.config_file.write_text(json.dumps(value))
                with self.assertRaises(TraceError) as error:
                    self.catalog.list(force=True)
                self.assertEqual(error.exception.code, "invalid_directory_config")


if __name__ == "__main__":
    unittest.main()
