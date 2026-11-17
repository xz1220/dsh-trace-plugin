"""Wall-clock corrections cannot override recorded order or explicit response identity."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/codex-dsh-trace/server"))

from fixtures import Fixture
from store import Store


class ClockOrderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        env = patch.dict(os.environ, {"CODEX_ROLLOUT_TRACE_ROOT": str(self.root / "none")})
        env.start()
        self.addCleanup(env.stop)
        self.store = Store(self.root / "config.json")
        self.store.catalog.default_root = self.root / "none"

    def bundle(self, name, started):
        fixture = Fixture(self.root / name, schema_version=2, started_at=started)
        path = fixture.root / "manifest.json"
        meta = json.loads(path.read_text())
        meta["trace_id"] = name
        path.write_text(json.dumps(meta))
        self.store.catalog.register(str(fixture.root))
        return fixture

    @staticmethod
    def append(fixture, time, kind, **values):
        event = fixture.event(kind, **values)
        event["wall_time_unix_ms"] = time
        with (fixture.root / "trace.jsonl").open("a") as stream:
            stream.write(json.dumps(event) + "\n")

    def request(self, fixture, name, time, previous=None, text=None, **values):
        raw = {
            "input": []
            if text is None
            else [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": text}],
                }
            ]
        }
        if previous:
            raw["previous_response_id"] = previous
        ref = fixture.payload(raw, "inference_request")
        self.append(
            fixture,
            time,
            "inference_started",
            inference_call_id=name,
            request_payload=ref,
            **values,
        )

    def complete(self, fixture, name, time, response_id):
        ref = fixture.payload({"output_items": []}, "inference_response")
        self.append(
            fixture,
            time,
            "inference_completed",
            inference_call_id=name,
            response_id=response_id,
            response_payload=ref,
        )

    def test_same_capture_keeps_parent_and_parallel_events_in_recorded_order(self):
        f = self.bundle("one", 1000)
        self.request(f, "root", 2000)
        self.append(f, 1500, "tool_call_started", tool_call_id="tool")
        self.request(f, "parallel", 1400, thread_id="worker")
        self.request(f, "root-next", 1800)
        rows = self.store.index("thread@thread-root").overview()["rows"]
        self.assertEqual(
            [r["sourceRowId"] for r in rows],
            ["request:root", "tool:tool", "request:parallel", "request:root-next"],
        )
        self.assertEqual([r["start"] for r in rows], [2000, 1500, 1400, 1800])
        self.assertEqual(rows[1]["parentId"], rows[0]["id"])

    def test_sources_still_interleave_by_time_instead_of_concatenating_bundles(self):
        a, b = self.bundle("a", 1000), self.bundle("b", 1100)
        self.request(a, "a1", 1200)
        self.request(a, "a2", 3000)
        self.request(b, "b1", 1500)
        self.request(b, "b2", 3500)
        rows = self.store.index("thread@thread-root").overview()["rows"]
        self.assertEqual(
            [r["id"] for r in rows],
            ["a:request:a1", "b:request:b1", "a:request:a2", "b:request:b2"],
        )

    def test_resumed_capture_clock_rollback_keeps_known_previous_context(self):
        a, b = self.bundle("before", 1000), self.bundle("after", 5000)
        self.request(a, "first", 2000, text="PREFIX")
        self.complete(a, "first", 2200, "response-first")
        self.request(b, "second", 1500, previous="response-first", text="INCREMENT")
        index = self.store.index("thread@thread-root")
        self.assertEqual(
            [r["id"] for r in index.overview()["rows"]],
            ["before:request:first", "after:request:second"],
        )
        context = index.context("after:request:second")
        self.assertTrue(context["complete"])
        self.assertEqual(
            [v["value"]["content"][0]["text"] for v in context["items"]], ["PREFIX", "INCREMENT"]
        )

    def test_unique_response_is_not_lost_when_recording_start_clock_also_moved_back(self):
        a, b = self.bundle("parent", 1000), self.bundle("resumed", 500)
        self.request(a, "first", 2000, text="PREFIX")
        self.complete(a, "first", 2200, "unique-response")
        self.request(b, "second", 600, previous="unique-response", text="INCREMENT")
        index = self.store.index("thread@thread-root")
        initial = index.overview()
        self.assertEqual(sum(i.metrics["payloadReads"] for i in self.store.indexes.values()), 0)
        context = index.context("resumed:request:second")
        self.assertTrue(context["complete"])
        self.assertEqual(context["previousRequestId"], "parent:request:first")
        self.assertEqual(
            [r["id"] for r in index.overview()["rows"]],
            ["parent:request:first", "resumed:request:second"],
        )
        self.assertTrue(index.delta(initial["revision"])["resync"])

    def test_ambiguous_cross_source_response_is_not_guessed_from_clock_order(self):
        a, b, c = self.bundle("a", 100), self.bundle("b", 1000), self.bundle("c", 500)
        for f, time in ((a, 200), (b, 1200)):
            self.request(f, "parent", time)
            self.complete(f, "parent", time + 10, "duplicate-response")
        self.request(c, "child", 600, previous="duplicate-response")
        context = self.store.index("thread@thread-root").context("c:request:child")
        self.assertFalse(context["complete"])
        self.assertEqual(context["missing"], "duplicate-response")

    def test_live_rollback_append_preserves_existing_positions_and_pagination(self):
        f = self.bundle("live", 1000)
        self.request(f, "first", 2000)
        self.request(f, "second", 2200)
        index = self.store.index("thread@thread-root")
        old = index.overview()
        self.request(f, "third", 1500)
        delta = index.delta(old["revision"])
        self.assertFalse(delta.get("resync", False))
        self.assertEqual([r["sourceRowId"] for r in delta["rows"]], ["request:third"])
        ids, before = [], None
        while True:
            page = index.overview(1, before)
            ids = [r["id"] for r in page["rows"]] + ids
            if not page["hasEarlier"]:
                break
            before = page["beforeSeq"]
        self.assertEqual(ids, ["live:request:first", "live:request:second", "live:request:third"])
        self.assertEqual(len(set(ids)), 3)

    def test_equal_time_order_is_deterministic_and_late_old_source_resyncs(self):
        b, a = self.bundle("b", 1000), self.bundle("a", 1000)
        self.request(b, "first", 1500)
        self.request(a, "first", 1500)
        index = self.store.index("thread@thread-root")
        old = index.overview()
        self.assertEqual([r["id"] for r in old["rows"]], ["a:request:first", "b:request:first"])
        early = self.bundle("earliest", 100)
        self.request(early, "first", 200)
        self.assertTrue(index.delta(old["revision"])["resync"])

    def test_projection_requests_resync_before_exposing_a_new_causal_order(self):
        a, b = self.bundle("parent", 1000), self.bundle("child", 500)
        self.request(a, "parent", 2000, text="PREFIX")
        self.complete(a, "parent", 2100, "parent-response")
        self.request(b, "child", 600, previous="parent-response", text="INCREMENT")
        index = self.store.index("thread@thread-root")
        original = index.overview()
        projector = self.store.projection("thread@thread-root")
        page = projector.page(row_ids=[row["id"] for row in original["rows"]])
        self.assertTrue(page["resync"])
        fresh = projector.page()
        self.assertFalse(fresh["resync"])
        self.assertEqual(fresh["rowIds"], ["parent:request:parent", "child:request:child"])
        self.assertEqual([r["number"] for r in fresh["requestNumbers"]], [1, 2])
        last = index.overview(1)
        earlier = index.overview(1, last["beforeSeq"])
        self.assertEqual(
            [r["id"] for r in earlier["rows"] + last["rows"]],
            ["parent:request:parent", "child:request:child"],
        )
        self.assertFalse(earlier["hasEarlier"])
        self.assertTrue(index.context("child:request:child")["complete"])

    def test_cycles_and_conflicts_do_not_override_recorded_order_or_invent_context(self):
        for cross_source in (False, True):
            with self.subTest(cross_source=cross_source):
                # Keep each case's ids and responses independent.
                suffix = str(cross_source)
                a = self.bundle("a" + suffix, 1000)
                b = self.bundle("b" + suffix, 2000) if cross_source else a
                self.request(
                    a, "first" + suffix, 1500, previous="second-response" + suffix, text="FIRST"
                )
                self.request(
                    b, "second" + suffix, 2500, previous="first-response" + suffix, text="SECOND"
                )
                self.complete(a, "first" + suffix, 2600, "first-response" + suffix)
                self.complete(b, "second" + suffix, 2700, "second-response" + suffix)
                index = self.store.index("thread@thread-root")
                for f, name in ((a, "first"), (b, "second")):
                    context = index.context(f.root.name + ":request:" + name + suffix)
                    self.assertFalse(context["complete"])
                if not cross_source:
                    rows = [
                        r for r in index.overview()["rows"] if r["sourceTraceId"] == a.root.name
                    ]
                    self.assertEqual(
                        [r["sourceRowId"] for r in rows],
                        ["request:first" + suffix, "request:second" + suffix],
                    )

    def test_late_duplicate_response_invalidates_an_already_resolved_context(self):
        a, b = self.bundle("parent", 100), self.bundle("child", 500)
        self.request(a, "parent", 200)
        self.complete(a, "parent", 300, "duplicate")
        self.request(b, "child", 600, previous="duplicate")
        index = self.store.index("thread@thread-root")
        self.assertTrue(index.context("child:request:child")["complete"])
        revision = index.overview()["revision"]
        other = self.bundle("other", 1000)
        self.request(other, "parent", 1200)
        self.complete(other, "parent", 1300, "duplicate")
        self.assertTrue(index.delta(revision)["resync"])
        self.assertFalse(index.context("child:request:child")["complete"])

    def test_backwards_completion_keeps_raw_times_and_reports_unknown_duration(self):
        f = self.bundle("clock", 1000)
        self.request(f, "request", 2000)
        self.complete(f, "request", 1500, "response")
        ref = f.payload({"output": "done"}, "tool_result")
        self.append(f, 2100, "tool_call_started", tool_call_id="tool")
        self.append(
            f, 1600, "tool_call_ended", tool_call_id="tool", status="completed", result_payload=ref
        )
        request = f.payload({"input": []}, "compaction_request")
        self.append(
            f,
            2200,
            "compaction_request_started",
            compaction_request_id="compact",
            request_payload=request,
        )
        self.append(
            f,
            1700,
            "compaction_request_completed",
            compaction_request_id="compact",
            response_payload=None,
        )
        index = self.store.index("thread@thread-root")
        rows = index.overview()["rows"]
        self.assertEqual(
            [(r["start"], r["end"]) for r in rows], [(2000, 1500), (2100, 1600), (2200, 1700)]
        )
        self.assertTrue(all(r["durationMs"] is None for r in rows))
        page = self.store.projection("thread@thread-root").page()
        selected = [c for c in page["cells"] if c["cellKey"] in ("assistant", "tool", "compaction")]
        self.assertTrue(all(c["timeSeconds"] is None and c["timingAnomaly"] for c in selected))
        self.assertTrue(all(r["status"] == "complete" for r in rows))
        metrics = next(c["assistantMetrics"] for c in selected if c["cellKey"] == "assistant")
        self.assertFalse(metrics["timingRecorded"])
        self.assertEqual((metrics["stepStartTime"], metrics["completedTime"]), (2000, 1500))

    def test_cross_capture_reference_conflicting_with_recorded_order_is_unknown(self):
        a, b = self.bundle("a", 100), self.bundle("b", 500)
        self.request(a, "first", 200, previous="b-response", text="FIRST")
        self.request(a, "later", 300, text="LATER")
        self.complete(a, "later", 350, "a-later-response")
        self.request(b, "other", 600, previous="a-later-response", text="OTHER")
        self.complete(b, "other", 650, "b-response")
        index = self.store.index("thread@thread-root")
        self.assertFalse(index.context("a:request:first")["complete"])
        rows = index.overview()["rows"]
        self.assertLess(
            next(r["seq"] for r in rows if r["id"] == "a:request:first"),
            next(r["seq"] for r in rows if r["id"] == "a:request:later"),
        )
        self.assertFalse(index.context("b:request:other")["complete"])

    def test_missing_reference_keeps_only_recorded_input_without_guessing_a_parent(self):
        f = self.bundle("missing", 100)
        self.request(f, "unrelated", 200, text="UNRELATED")
        self.complete(f, "unrelated", 250, "other-response")
        self.request(f, "current", 300, previous="not-recorded", text="KNOWN")
        context = self.store.index("thread@thread-root").context("missing:request:current")
        self.assertFalse(context["complete"])
        self.assertEqual(context["missing"], "not-recorded")
        self.assertEqual([v["value"]["content"][0]["text"] for v in context["items"]], ["KNOWN"])

    def test_turn_numbers_follow_recorded_rows_when_turn_wall_clock_moves_back(self):
        f = self.bundle("turns", 1000)
        self.append(f, 2000, "codex_turn_started", codex_turn_id="first-turn")
        self.request(f, "first", 2100, codex_turn_id="first-turn")
        self.append(f, 1500, "codex_turn_started", codex_turn_id="second-turn")
        self.request(f, "second", 1600, codex_turn_id="second-turn")
        page = self.store.projection("thread@thread-root").page()
        self.assertEqual(
            [(r["rowId"], r["turn"]) for r in page["requestNumbers"]],
            [("turns:request:first", 1), ("turns:request:second", 2)],
        )

    def test_projection_page_does_not_eagerly_read_the_whole_local_response_chain(self):
        f = self.bundle("many", 1000)
        for number in range(50):
            previous = f"r{number - 1}" if number else None
            self.request(f, str(number), 2000 + number * 10, previous=previous)
            self.complete(f, str(number), 2001 + number * 10, f"r{number}")
        index = self.store.index("thread@thread-root")
        index.overview()
        self.assertEqual(sum(i.metrics["payloadReads"] for i in self.store.indexes.values()), 0)
        projector = self.store.projection("thread@thread-root")
        page = projector.page(row_ids=[f"many:request:{number}" for number in range(40, 50)])
        self.assertFalse(page["resync"])
        # Each visible request and response plus the history-turn metadata prefix.
        self.assertLessEqual(
            sum(i.metrics["payloadReads"] for i in self.store.indexes.values()), 21
        )
        self.assertTrue(index.context("many:request:49")["complete"])
