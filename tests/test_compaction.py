"""Recorded compaction application metadata stays separate from request history."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_store import Fixture
from store import Store


class CompactionInstalledTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        env = patch.dict(
            os.environ, {"CODEX_ROLLOUT_TRACE_ROOT": str(self.root / "no-environment")}
        )
        env.start()
        self.addCleanup(env.stop)
        self.fixture = Fixture(self.root / "bundle", schema_version=2)
        self.store = Store(self.root / "config.json")
        self.store.catalog.default_root = self.root / "no-default"
        self.store.catalog.register(str(self.fixture.root))

    def compaction(
        self,
        fixture=None,
        *,
        request_id="attempt-one",
        compaction_id="compact-one",
        status="completed",
        thread="thread-root",
    ):
        fixture = fixture or self.fixture
        raw = {
            "model": "recorded-model",
            "input": [{"type": "message", "role": "user", "content": "Recorded input"}],
        }
        request = fixture.payload(raw, "compaction_request")
        started = fixture.append(
            "compaction_request_started",
            compaction_id=compaction_id,
            compaction_request_id=request_id,
            thread_id=thread,
            codex_turn_id="turn-1",
            request_payload=request,
        )
        response = {
            "output_items": [
                {
                    "type": "compaction",
                    "id": compaction_id,
                    "encrypted_content": "opaque-recorded-data",
                }
            ]
        }
        ref = fixture.payload(response, "compaction_response")
        completed = fixture.append(
            "compaction_request_" + status,
            compaction_id=compaction_id,
            compaction_request_id=request_id,
            response_payload=ref,
        )
        return raw, response, started, completed

    def install(self, fixture=None, *, compaction_id="compact-one"):
        fixture = fixture or self.fixture
        checkpoint = {
            "input_history": [
                {"type": "message", "role": "assistant", "content": "PRIVATE_CHECKPOINT_BODY"}
            ],
            "replacement_history": [
                {"type": "compaction", "encrypted_content": "opaque-replacement"}
            ],
        }
        ref = fixture.payload(checkpoint, "compaction_checkpoint")
        event = fixture.append(
            "compaction_installed", compaction_id=compaction_id, checkpoint_payload=ref
        )
        return ref, event

    def test_install_updates_matching_success_without_changing_duration_or_raw_payloads(self):
        raw, response, started, completed = self.compaction()
        ref, event = self.install()
        index = self.store.index("trace-test")
        overview = index.overview()
        row = index.get_row("compaction:attempt-one")
        public = overview["rows"][0]
        self.assertEqual(overview["totalRows"], 1)
        self.assertEqual(overview["requestCount"], 1)
        self.assertTrue(public["compactionApplied"])
        self.assertEqual(public["installedAt"], event["wall_time_unix_ms"])
        self.assertEqual(row["start"], started["wall_time_unix_ms"])
        self.assertEqual(row["end"], completed["wall_time_unix_ms"])
        self.assertEqual(
            public["durationMs"], completed["wall_time_unix_ms"] - started["wall_time_unix_ms"]
        )
        self.assertEqual(row["_checkpoint"], ref)
        self.assertEqual(
            json.loads(self.store.text("trace-test", row["id"], "raw_request")["text"]), raw
        )
        self.assertEqual(
            json.loads(self.store.text("trace-test", row["id"], "response")["text"]), response
        )

    def test_index_and_overview_keep_checkpoint_body_lazy(self):
        self.compaction()
        self.install()
        index = self.store.index("trace-test")
        overview = index.overview()
        self.assertEqual(index.metrics["payloadReads"], 0)
        self.assertNotIn("PRIVATE_CHECKPOINT_BODY", json.dumps(overview))
        self.assertNotIn("_checkpoint", json.dumps(overview))
        index.delta(overview["revision"])
        self.assertEqual(index.metrics["payloadReads"], 0)
        self.assertEqual(
            len(
                index.payload(index.get_row("compaction:attempt-one")["_checkpoint"])[
                    "replacement_history"
                ]
            ),
            1,
        )
        self.assertEqual(index.metrics["payloadReads"], 1)

    def test_compaction_cell_keeps_raw_output_separate_from_display_facts(self):
        raw, response, _, _ = self.compaction()
        self.install()
        projector = self.store.projection("trace-test")
        cell = next(cell for cell in projector.page()["cells"] if cell["kind"] == "compacted")
        self.assertTrue(cell["compactionApplied"])
        self.assertNotIn("compactionInfo", cell)
        detail = projector.detail("compaction:attempt-one", "compaction")
        self.assertTrue(detail["compactionInfo"]["applied"])
        self.assertEqual(json.loads(detail["sourceBlocks"][0]["content"]), response)
        self.assertEqual(json.loads(detail["outputDetail"]), response)
        self.assertNotIn("PRIVATE_CHECKPOINT_BODY", json.dumps(detail))

    def test_install_append_marks_existing_row_changed(self):
        self.compaction()
        index = self.store.index("trace-test")
        before = index.overview()
        self.install()
        delta = index.delta(before["revision"])
        self.assertEqual(len(delta["rows"]), 1)
        self.assertEqual(delta["rows"][0]["id"], "compaction:attempt-one")
        self.assertTrue(delta["rows"][0]["compactionApplied"])

    def test_unmatched_install_does_not_attach_to_another_compaction(self):
        self.compaction()
        self.install(compaction_id="unrelated")
        index = self.store.index("trace-test")
        overview = index.overview()
        self.assertEqual(overview["totalRows"], 1)
        self.assertNotIn("compactionApplied", overview["rows"][0])
        self.assertNotIn("_checkpoint", index.get_row("compaction:attempt-one"))

    def test_install_without_a_recorded_request_does_not_create_an_invented_row(self):
        self.install()
        self.assertEqual(self.store.index("trace-test").overview()["totalRows"], 0)

    def test_failed_request_is_not_treated_as_applied(self):
        self.compaction(status="failed")
        self.install()
        row = self.store.index("trace-test").overview()["rows"][0]
        self.assertEqual(row["status"], "error")
        self.assertNotIn("compactionApplied", row)

    def test_incomplete_request_is_not_treated_as_applied(self):
        request = self.fixture.payload({"input": []}, "compaction_request")
        self.fixture.append(
            "compaction_request_started",
            compaction_id="compact-one",
            compaction_request_id="running-attempt",
            request_payload=request,
        )
        self.install()
        row = self.store.index("trace-test").overview()["rows"][0]
        self.assertEqual(row["status"], "running")
        self.assertNotIn("compactionApplied", row)

    def test_ambiguous_successful_attempts_are_not_guessed(self):
        self.compaction(request_id="attempt-one")
        self.compaction(request_id="attempt-two")
        self.install()
        rows = self.store.index("trace-test").overview()["rows"]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all("compactionApplied" not in row for row in rows))

    def test_same_id_in_another_thread_does_not_receive_the_checkpoint(self):
        self.compaction(thread="thread-child")
        self.install()
        row = self.store.index("trace-test").overview()["rows"][0]
        self.assertNotIn("compactionApplied", row)

    def test_repeated_install_keeps_first_application_time_and_reference(self):
        self.compaction()
        first_ref, first_event = self.install()
        self.install()
        row = self.store.index("trace-test").get_row("compaction:attempt-one")
        self.assertEqual(row["_checkpoint"], first_ref)
        self.assertEqual(row["installedAt"], first_event["wall_time_unix_ms"])

    def test_missing_compaction_id_is_not_used_for_correlation(self):
        self.compaction(compaction_id=None)
        self.install(compaction_id=None)
        row = self.store.index("trace-test").overview()["rows"][0]
        self.assertNotIn("compactionApplied", row)

    def test_thread_view_qualifies_checkpoint_refs_to_their_recording(self):
        self.compaction()
        self.install()
        other = Fixture(self.root / "resumed", schema_version=2, started_at=10000)
        path = other.root / "manifest.json"
        meta = json.loads(path.read_text())
        meta["trace_id"] = "trace-resumed"
        path.write_text(json.dumps(meta))
        self.compaction(other)
        self.install(other)
        checkpoint = other.root / "payloads/3.json"
        value = json.loads(checkpoint.read_text())
        value["replacement_history"].append(
            {"type": "message", "role": "user", "content": "RESUMED_RECORDING_ONLY"}
        )
        checkpoint.write_text(json.dumps(value))
        self.store.catalog.register(str(other.root))
        index = self.store.index("thread@thread-root")
        overview = index.overview()
        self.assertEqual(overview["requestCount"], 2)
        for source in ("trace-test", "trace-resumed"):
            row = index.get_row(source + ":compaction:attempt-one")
            self.assertTrue(row["compactionApplied"])
            self.assertEqual(row["_checkpoint"]["_sourceTraceId"], source)
            self.assertEqual(
                index.payload(row["_checkpoint"])["replacement_history"][0]["type"], "compaction"
            )
            facts = self.store.details("thread@thread-root", row["id"])["compaction"]
            self.assertEqual(facts["after"]["items"], 1 if source == "trace-test" else 2)

    def test_detail_reports_recorded_replacement_counts_without_exposing_ciphertext(self):
        self.compaction()
        self.install()
        data = self.store.details("trace-test", "compaction:attempt-one")["compaction"]
        self.assertTrue(data["applied"])
        self.assertIsNotNone(data["installedAt"])
        self.assertEqual(
            data["before"], {"items": 1, "roles": {"assistant": 1}, "encryptedItems": 0}
        )
        self.assertEqual(data["after"], {"items": 1, "roles": {}, "encryptedItems": 1})
        self.assertEqual(data["output"], {"items": 1, "roles": {}, "encryptedItems": 1})
        self.assertEqual(data["readableSummary"], "")
        self.assertNotIn("opaque-", json.dumps(data))

    def test_completed_request_without_installed_checkpoint_does_not_claim_application(self):
        self.compaction()
        data = self.store.details("trace-test", "compaction:attempt-one")["compaction"]
        self.assertFalse(data["applied"])
        self.assertIsNone(data["installedAt"])
        self.assertEqual(data["before"], {"items": 1, "roles": {"user": 1}, "encryptedItems": 0})
        self.assertIsNone(data["after"])

    def test_detail_keeps_a_bounded_readable_summary_with_complete_raw_response(self):
        self.compaction()
        text = "Recorded summary 🌱 " * 400
        path = self.fixture.root / "payloads/2.json"
        response = json.loads(path.read_text())
        response["output_items"][0]["summary"] = [{"type": "summary_text", "text": text}]
        path.write_text(json.dumps(response))
        data = self.store.details("trace-test", "compaction:attempt-one")["compaction"]
        self.assertEqual(data["readableSummary"], text[:4096])
        self.assertEqual(data["readableSummaryChars"], len(text))
        self.assertTrue(data["readableSummaryTruncated"])
        raw = json.loads(
            self.store.text("trace-test", "compaction:attempt-one", "response")["text"]
        )
        self.assertEqual(raw["output_items"][0]["summary"][0]["text"], text)


if __name__ == "__main__":
    unittest.main()
