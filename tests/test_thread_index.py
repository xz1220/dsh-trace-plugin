import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/codex-dsh-trace/server"))

from store import Store, TraceError
from test_store import Fixture


class ThreadIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        env = patch.dict(os.environ, {"CODEX_ROLLOUT_TRACE_ROOT": str(self.root / "no-env")})
        env.start()
        self.addCleanup(env.stop)
        self.store = Store(self.root / "config.json")
        self.store.catalog.default_root = self.root / "no-default"
        self.before = self.bundle("before", 1000)
        self.before.conversation("BEFORE_CONTEXT")
        output = self.before.payload(
            {
                "output_items": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "id": "before-answer",
                        "content": [{"type": "output_text", "text": "BEFORE_ANSWER"}],
                    }
                ]
            },
            "inference_response",
        )
        self.before.append(
            "inference_completed",
            inference_call_id="second",
            response_id="resp-second",
            response_payload=output,
        )
        self.before.append("rollout_ended", status="completed")
        self.after = self.bundle("after", 5000)

    def bundle(self, name, started):
        value = Fixture(self.root / name, schema_version=2, started_at=started)
        path = value.root / "manifest.json"
        meta = json.loads(path.read_text())
        meta["trace_id"] = name
        path.write_text(json.dumps(meta))
        self.store.catalog.register(str(value.root))
        return value

    def test_empty_new_recording_keeps_history_and_append_keeps_the_same_view_identity(self):
        opened = self.store.open(thread_id="thread-root")
        identity = opened["trace"]["id"]
        self.assertEqual(opened["requestCount"], 2)
        self.assertEqual(opened["trace"]["recordingCount"], 2)
        prior = [row["id"] for row in opened["rows"]]
        revision = opened["revision"]
        request = self.after.payload(
            {
                "input": [
                    {
                        "type": "message",
                        "role": "user",
                        "id": "new-user",
                        "content": [{"type": "input_text", "text": "NEW_MESSAGE"}],
                    }
                ]
            },
            "inference_request",
        )
        self.after.append("codex_turn_started", thread_id="thread-root", codex_turn_id="new-turn")
        self.after.append(
            "inference_started",
            inference_call_id="first",
            thread_id="thread-root",
            codex_turn_id="new-turn",
            request_payload=request,
        )
        self.assertEqual(self.store.binding("thread-root")["trace"]["id"], identity)
        index = self.store.index(identity)
        delta = index.delta(revision)
        self.assertFalse(delta.get("resync", False))
        self.assertEqual(len(delta["rows"]), 1)
        all_rows = index.overview()["rows"]
        self.assertEqual([row["id"] for row in all_rows[: len(prior)]], prior)
        self.assertEqual(index.overview()["requestCount"], 3)
        self.assertEqual(index.overview()["toolCount"], 1)
        self.assertEqual(self.store.open(trace_id="before")["requestCount"], 2)

    def test_new_manifest_before_log_creation_does_not_hide_existing_history(self):
        path = self.after.root / "trace.jsonl"
        path.unlink()
        opened = self.store.open(thread_id="thread-root")
        self.assertEqual(opened["requestCount"], 2)
        self.assertEqual(opened["trace"]["recordingCount"], 1)
        path.touch()
        self.store.binding("thread-root")
        self.assertEqual(self.store.open(thread_id="thread-root")["trace"]["recordingCount"], 2)

    def test_duplicate_source_row_response_and_tool_ids_do_not_collide(self):
        self.after.conversation("AFTER_CONTEXT")
        data = self.store.open(thread_id="thread-root")
        identity = data["trace"]["id"]
        self.assertEqual(data["requestCount"], 4)
        self.assertEqual(data["toolCount"], 2)
        self.assertEqual(len({row["id"] for row in data["rows"]}), len(data["rows"]))
        before = self.store.text(identity, "before:request:second", "full_context")["text"]
        after = self.store.text(identity, "after:request:second", "full_context")["text"]
        self.assertIn("BEFORE_CONTEXT", before)
        self.assertNotIn("AFTER_CONTEXT", before)
        self.assertIn("AFTER_CONTEXT", after)
        self.assertNotIn("BEFORE_CONTEXT", after)
        self.assertEqual(
            self.store.locate_call(identity, "before:call-1")["sourceTraceId"], "before"
        )
        self.assertEqual(self.store.locate_call(identity, "after:call-1")["sourceTraceId"], "after")
        with self.assertRaises(TraceError):
            self.store.locate_call(identity, "call-1")
        cells = self.store.projection(identity).page()["cells"]
        calls = [cell["callId"] for cell in cells if cell["kind"] == "tool"]
        self.assertIn("before:call-1", calls)
        self.assertIn("after:call-1", calls)

    def test_previous_response_can_cross_recording_boundaries_without_changing_raw_request(self):
        raw = {
            "previous_response_id": "resp-second",
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "id": "next",
                    "content": [{"type": "input_text", "text": "FOLLOW_UP"}],
                }
            ],
        }
        request = self.after.payload(raw, "inference_request")
        self.after.append(
            "inference_started",
            inference_call_id="follow",
            thread_id="thread-root",
            request_payload=request,
        )
        opened = self.store.open(thread_id="thread-root")
        identity = opened["trace"]["id"]
        detail = self.store.details(identity, "after:request:follow")
        self.assertTrue(detail["context"]["complete"])
        text = self.store.text(identity, "after:request:follow", "full_context")["text"]
        self.assertIn("BEFORE_CONTEXT", text)
        self.assertIn("BEFORE_ANSWER", text)
        self.assertIn("FOLLOW_UP", text)
        self.assertEqual(
            json.loads(self.store.text(identity, "after:request:follow", "raw_request")["text"]),
            raw,
        )

    def test_history_pagination_does_not_duplicate_records_and_warm_poll_does_not_read_bodies(self):
        self.after.conversation("AFTER_CONTEXT")
        opened = self.store.open(thread_id="thread-root")
        index = self.store.index(opened["trace"]["id"])
        ids = []
        before = None
        while True:
            page = index.overview(2, before)
            ids = [row["id"] for row in page["rows"]] + ids
            if not page["hasEarlier"]:
                break
            before = page["beforeSeq"]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), opened["totalRows"])
        reads = {key: dict(value.metrics) for key, value in self.store.indexes.items()}
        self.assertTrue(index.delta(opened["revision"])["unchanged"])
        self.store.binding("thread-root")
        self.assertEqual(
            reads, {key: dict(value.metrics) for key, value in self.store.indexes.items()}
        )

    def test_unrelated_root_is_not_merged(self):
        other = self.bundle("other", 9000)
        path = other.root / "manifest.json"
        meta = json.loads(path.read_text())
        meta["root_thread_id"] = "other-root"
        path.write_text(json.dumps(meta))
        other.conversation("OTHER_CONTEXT")
        opened = self.store.open(thread_id="thread-root")
        self.assertEqual(opened["trace"]["recordingCount"], 2)
        self.assertFalse(any(row["sourceTraceId"] == "other" for row in opened["rows"]))

    def test_aggregate_limit_is_explicit_and_individual_recordings_remain_readable(self):
        from thread_index import ThreadIndex

        with patch("thread_index.MAX_LOG", 32):
            with self.assertRaisesRegex(TraceError, "总索引"):
                ThreadIndex(self.store, "thread-root").overview()
        self.assertEqual(self.store.open(trace_id="before")["requestCount"], 2)

    def test_explicit_thread_view_reopens_and_rejects_a_conflicting_root(self):
        opened = self.store.open(thread_id="thread-root")
        self.assertEqual(
            self.store.open(trace_id=opened["trace"]["id"])["trace"]["id"], opened["trace"]["id"]
        )
        with self.assertRaises(TraceError):
            self.store.open(trace_id=opened["trace"]["id"], thread_id="other-root")

    def test_rewritten_source_forces_a_resync_instead_of_retaining_deleted_events(self):
        opened = self.store.open(thread_id="thread-root")
        index = self.store.index(opened["trace"]["id"])
        (self.before.root / "trace.jsonl").write_text("")
        self.assertTrue(index.delta(opened["revision"])["resync"])
        self.assertEqual(index.overview()["totalRows"], 0)

    def test_cached_projection_rebuilds_positions_when_older_recording_is_added(self):
        opened = self.store.open(thread_id="thread-root")
        identity = opened["trace"]["id"]
        projector = self.store.projection(identity)
        old = projector.page(row_ids=["before:request:first"])
        earlier = self.bundle("earliest", 100)
        earlier.conversation("EARLIEST_CONTEXT")
        fresh = projector.page(row_ids=["before:request:first"])
        self.assertGreater(fresh["requestNumbers"][0]["seq"], old["requestNumbers"][0]["seq"])
        self.assertEqual(
            {cell["seq"] for cell in fresh["cells"]}, {fresh["requestNumbers"][0]["seq"]}
        )
