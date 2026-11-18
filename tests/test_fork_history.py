"""Forked request context is inherited input, not a second conversation ledger."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/codex-dsh-trace/server"))

from fixtures import Fixture
from store import Store, TraceError


class ForkHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = Fixture(self.root / "bundle")
        isolated = patch.dict(
            os.environ, {"CODEX_ROLLOUT_TRACE_ROOT": str(self.root / "no-environment")}
        )
        isolated.start()
        self.addCleanup(isolated.stop)
        self.store = Store(self.root / "config.json")
        self.store.catalog.default_root = self.root / "no-default"
        self.store.catalog.register(str(self.fixture.root))
        self.thread("thread-root", "/root")

    @staticmethod
    def message(role, identity, text, turn=None):
        result = {
            "type": "message",
            "role": role,
            "id": identity,
            "content": [
                {"type": "output_text" if role == "assistant" else "input_text", "text": text}
            ],
        }
        if turn is not None:
            result["internal_chat_message_metadata_passthrough"] = {"turn_id": turn}
        return result

    def append(self, kind, thread="thread-root", fixture=None, **values):
        fixture = fixture or self.fixture
        event = fixture.event(kind, **values)
        event["thread_id"] = thread
        if values.get("codex_turn_id"):
            event["codex_turn_id"] = values["codex_turn_id"]
        with (fixture.root / "trace.jsonl").open("a") as stream:
            stream.write(json.dumps(event) + "\n")
        return event

    def thread(self, identity, path, fixture=None):
        self.append(
            "thread_started", thread=identity, fixture=fixture, thread_id=identity, agent_path=path
        )

    def request(self, identity, inputs, thread="thread-root", turn="main-turn", fixture=None):
        fixture = fixture or self.fixture
        self.append(
            "codex_turn_started",
            thread=thread,
            fixture=fixture,
            thread_id=thread,
            codex_turn_id=turn,
        )
        payload = fixture.payload({"input": inputs}, "inference_request")
        self.append(
            "inference_started",
            thread=thread,
            fixture=fixture,
            inference_call_id=identity,
            thread_id=thread,
            codex_turn_id=turn,
            request_payload=payload,
        )

    def reply(self, identity, messages, thread="thread-root", fixture=None):
        fixture = fixture or self.fixture
        payload = fixture.payload({"output_items": messages}, "inference_response")
        self.append(
            "inference_completed",
            thread=thread,
            fixture=fixture,
            inference_call_id=identity,
            response_id="response-" + identity,
            response_payload=payload,
        )

    def projection(self):
        return self.store.projection("trace-test")

    def input_cells(self, projector, row_id):
        row = projector.index.get_row(row_id)
        return [cell for cell in projector.cells(row) if cell["cellKey"].startswith("input:")]

    def test_child_first_snapshot_does_not_redraw_seventeen_parent_turns(self):
        history = []
        for number in range(1, 18):
            history.extend(
                [
                    self.message(
                        "user", f"user-{number}", f"PARENT_USER_{number}", f"turn-{number}"
                    ),
                    self.message(
                        "assistant", f"answer-{number}", f"PARENT_ANSWER_{number}", f"turn-{number}"
                    ),
                ]
            )
        self.request("parent", history)
        parent_reply = self.message(
            "assistant", "parent-current", "PARENT_CURRENT_REPLY", "main-turn"
        )
        self.reply("parent", [parent_reply])
        self.thread("child", "/root/review")
        task = self.message("user", "child-task", "CHILD_NEW_TASK", "child-turn")
        self.request(
            "child-first", [*history, parent_reply, task], thread="child", turn="child-turn"
        )
        self.reply(
            "child-first",
            [self.message("assistant", "child-answer", "CHILD_REPLY", "child-turn")],
            thread="child",
        )
        projector = self.projection()
        cells = projector.page()["cells"]
        for number in range(1, 18):
            self.assertEqual(
                sum(cell.get("previewMarkdown") == f"PARENT_USER_{number}" for cell in cells), 1
            )
            self.assertEqual(
                sum(cell.get("previewMarkdown") == f"PARENT_ANSWER_{number}" for cell in cells), 1
            )
        child = self.input_cells(projector, "request:child-first")
        self.assertEqual([cell["previewMarkdown"] for cell in child], ["CHILD_NEW_TASK"])
        self.assertTrue(child[0]["opensTurn"])
        self.assertEqual(
            sum(cell.get("previewMarkdown") == "PARENT_CURRENT_REPLY" for cell in cells), 1
        )
        self.assertEqual(sum(cell.get("previewMarkdown") == "CHILD_REPLY" for cell in cells), 1)

    def test_same_text_with_a_distinct_child_identity_is_a_new_message(self):
        old = self.message("user", "parent-user", "REPEATED_TEXT", "main-turn")
        self.request("parent", [old])
        self.thread("child", "/root/review")
        own = self.message("user", "child-user", "REPEATED_TEXT", "child-turn")
        self.request("child", [old, own], thread="child", turn="child-turn")
        projector = self.projection()
        child = self.input_cells(projector, "request:child")
        self.assertEqual([cell["previewMarkdown"] for cell in child], ["REPEATED_TEXT"])
        self.assertTrue(child[0]["opensTurn"])
        self.assertEqual(
            sum(
                cell.get("previewMarkdown") == "REPEATED_TEXT" for cell in projector.page()["cells"]
            ),
            2,
        )

    def test_inherited_user_with_recorded_other_turn_never_opens_the_child_turn(self):
        self.thread("child", "unknown-path")
        inherited = self.message("user", "parent-user", "UNVERIFIED_INHERITED_INPUT", "main-turn")
        self.request("child", [inherited], thread="child", turn="child-turn")
        child = self.input_cells(self.projection(), "request:child")
        self.assertEqual(len(child), 1)
        self.assertFalse(child[0]["opensTurn"])
        self.assertTrue(child[0]["inputHistory"])

    def test_last_user_without_turn_metadata_still_opens_its_turn(self):
        self.thread("child", "unknown-path")
        self.request(
            "child",
            [self.message("user", "new-user", "OWN_TASK_WITHOUT_TURN")],
            thread="child",
            turn="child-turn",
        )
        child = self.input_cells(self.projection(), "request:child")
        self.assertTrue(child[0]["opensTurn"])

    def test_sibling_agent_history_is_not_used_to_deduplicate_a_child(self):
        self.request("parent", [self.message("user", "root-input", "ROOT_ONLY", "main-turn")])
        self.thread("sibling", "/root/other")
        sibling = self.message("user", "sibling-input", "SIBLING_ONLY", "sibling-turn")
        self.request("sibling", [sibling], thread="sibling", turn="sibling-turn")
        self.thread("child", "/root/review")
        self.request("child", [sibling], thread="child", turn="child-turn")
        child = self.input_cells(self.projection(), "request:child")
        self.assertEqual([cell["previewMarkdown"] for cell in child], ["SIBLING_ONLY"])

    def test_nested_fork_uses_its_nearest_recorded_ancestor(self):
        root = self.message("user", "root-input", "ROOT_ONLY", "main-turn")
        self.request("root", [root])
        self.thread("manager", "/root/manager")
        manager = self.message("user", "manager-input", "MANAGER_ONLY", "manager-turn")
        self.request("manager", [root, manager], thread="manager", turn="manager-turn")
        reply = self.message("assistant", "manager-answer", "MANAGER_REPLY", "manager-turn")
        self.reply("manager", [reply], thread="manager")
        self.thread("worker", "/root/manager/worker")
        task = self.message("user", "worker-task", "WORKER_TASK", "worker-turn")
        self.request("worker", [root, manager, reply, task], thread="worker", turn="worker-turn")
        worker = self.input_cells(self.projection(), "request:worker")
        self.assertEqual([cell["previewMarkdown"] for cell in worker], ["WORKER_TASK"])

    def test_a_parent_request_recorded_after_the_fork_is_not_borrowed(self):
        self.thread("child", "/root/review")
        message = self.message("user", "shared-id", "CHILD_RECORDED_FIRST", "main-turn")
        self.request("child", [message], thread="child", turn="child-turn")
        self.request("parent", [message])
        child = self.input_cells(self.projection(), "request:child")
        self.assertEqual([cell["previewMarkdown"] for cell in child], ["CHILD_RECORDED_FIRST"])

    def test_an_ancestor_response_completed_after_the_fork_is_not_borrowed(self):
        self.request("parent", [self.message("user", "parent-input", "PARENT_INPUT", "main-turn")])
        response = self.message(
            "assistant", "later-response", "RESPONSE_COMPLETED_LATER", "main-turn"
        )
        self.thread("child", "/root/review")
        self.request("child", [response], thread="child", turn="child-turn")
        self.reply("parent", [response])
        child = self.input_cells(self.projection(), "request:child")
        self.assertEqual([cell["previewMarkdown"] for cell in child], ["RESPONSE_COMPLETED_LATER"])

    def test_an_ancestor_response_recorded_later_in_the_same_millisecond_is_not_borrowed(self):
        self.request("parent", [self.message("user", "parent-input", "PARENT_INPUT", "main-turn")])
        response = self.message(
            "assistant", "same-time-response", "SAME_MILLISECOND_LATER_RESPONSE", "main-turn"
        )
        self.thread("child", "/root/review")
        self.request("child", [response], thread="child", turn="child-turn")
        self.reply("parent", [response])
        path = self.fixture.root / "trace.jsonl"
        events = [json.loads(line) for line in path.read_text().splitlines()]
        started = next(
            event["wall_time_unix_ms"]
            for event in events
            if event["payload"].get("inference_call_id") == "child"
        )
        for event in events:
            if event["payload"]["type"] == "inference_completed":
                event["wall_time_unix_ms"] = started
        path.write_text("".join(json.dumps(event) + "\n" for event in events))
        child = self.input_cells(self.projection(), "request:child")
        self.assertEqual(
            [cell["previewMarkdown"] for cell in child], ["SAME_MILLISECOND_LATER_RESPONSE"]
        )

    def test_unknown_agent_relationship_keeps_the_recorded_input(self):
        inherited = self.message(
            "user", "old-user", "RECORD_WITHOUT_CONFIRMED_ANCESTRY", "main-turn"
        )
        self.request("parent", [inherited])
        self.thread("child", "/different-root/review")
        self.request("child", [inherited], thread="child", turn="child-turn")
        child = self.input_cells(self.projection(), "request:child")
        self.assertEqual(
            [cell["previewMarkdown"] for cell in child], ["RECORD_WITHOUT_CONFIRMED_ANCESTRY"]
        )

    def resumed_bundle(self, name="resumed", started_at=10000):
        fixture = Fixture(self.root / name, schema_version=2, started_at=started_at)
        path = fixture.root / "manifest.json"
        meta = json.loads(path.read_text())
        meta["trace_id"] = name
        path.write_text(json.dumps(meta))
        self.store.catalog.register(str(fixture.root))
        return fixture

    def test_root_aggregate_preserves_cross_recording_history_without_child_rows(self):
        parent = self.message("user", "parent-user", "PARENT_BEFORE_RESUME", "main-turn")
        self.request("parent", [parent])
        resumed = self.resumed_bundle()
        self.thread("thread-root", "/root", fixture=resumed)
        self.request(
            "root-resumed",
            [self.message("user", "root-follow-up", "ROOT_AFTER_RESUME", "resumed-root-turn")],
            turn="resumed-root-turn",
            fixture=resumed,
        )
        self.thread("child", "/root/review", fixture=resumed)
        self.request(
            "child",
            [parent, self.message("user", "child-task", "RESUMED_CHILD_TASK", "child-turn")],
            thread="child",
            turn="child-turn",
            fixture=resumed,
        )
        projector = self.store.projection("thread@thread-root")
        page = projector.page()
        self.assertEqual(
            page["rowIds"], ["trace-test:request:parent", "resumed:request:root-resumed"]
        )
        self.assertEqual(
            {row["threadId"] for row in projector.index.rows.values()}, {"thread-root"}
        )
        self.assertEqual(set(projector.index.turns), {"main-turn", "resumed-root-turn"})
        self.assertEqual(projector.index.threads, {"thread-root": "/root"})
        texts = [cell.get("previewMarkdown") for cell in page["cells"]]
        self.assertEqual(texts.count("PARENT_BEFORE_RESUME"), 1)
        self.assertEqual(texts.count("ROOT_AFTER_RESUME"), 1)
        self.assertNotIn("RESUMED_CHILD_TASK", texts)
        with self.assertRaises(TraceError) as missing:
            self.input_cells(projector, "resumed:request:child")
        self.assertEqual(missing.exception.code, "record_not_found")
        # The explicit capture remains a mixed-thread diagnostic entry point.
        capture = self.store.projection("resumed")
        self.assertEqual(
            [cell["previewMarkdown"] for cell in self.input_cells(capture, "request:child")],
            ["PARENT_BEFORE_RESUME", "RESUMED_CHILD_TASK"],
        )

    def test_other_root_is_excluded_and_capture_does_not_inherit_its_agent_history(self):
        self.request("root", [self.message("user", "root-input", "ROOT_CHAT_INPUT", "main-turn")])
        inherited = self.message("user", "matching-id", "MESSAGE_FROM_OTHER_CHAT", "main-turn")
        other = self.resumed_bundle("other-chat", started_at=100)
        path = other.root / "manifest.json"
        meta = json.loads(path.read_text())
        meta["root_thread_id"] = "other-root"
        path.write_text(json.dumps(meta))
        self.thread("other-root", "/root", fixture=other)
        self.request("other", [inherited], thread="other-root", fixture=other)
        self.thread("child", "/root/review")
        self.request("child", [inherited], thread="child", turn="child-turn")
        projector = self.store.projection("thread@thread-root")
        page = projector.page()
        self.assertEqual(page["rowIds"], ["trace-test:request:root"])
        self.assertEqual(
            {row["threadId"] for row in projector.index.rows.values()}, {"thread-root"}
        )
        self.assertEqual(set(projector.index.turns), {"main-turn"})
        self.assertEqual(projector.index.threads, {"thread-root": "/root"})
        self.assertFalse(
            any(row.get("sourceTraceId") == "other-chat" for row in projector.index.rows.values())
        )
        self.assertNotIn(
            "MESSAGE_FROM_OTHER_CHAT", [cell.get("previewMarkdown") for cell in page["cells"]]
        )
        with self.assertRaises(TraceError) as missing:
            self.input_cells(projector, "trace-test:request:child")
        self.assertEqual(missing.exception.code, "record_not_found")
        # Matching agent paths in another root do not justify dropping recorded
        # input from the explicit capture's diagnostic child view.
        capture = self.projection()
        self.assertEqual(
            [cell["previewMarkdown"] for cell in self.input_cells(capture, "request:child")],
            ["MESSAGE_FROM_OTHER_CHAT"],
        )

    def test_late_older_root_rebuilds_cached_positions_without_restoring_child_rows(self):
        inherited = self.message(
            "user", "parent-user", "OLDER_PARENT_DISCOVERED_LATER", "main-turn"
        )
        resumed = self.resumed_bundle()
        self.thread("thread-root", "/root", fixture=resumed)
        self.request(
            "root-resumed",
            [self.message("user", "root-follow-up", "ROOT_AFTER_RESUME", "resumed-root-turn")],
            turn="resumed-root-turn",
            fixture=resumed,
        )
        self.thread("child", "/root/review", fixture=resumed)
        self.request(
            "child",
            [inherited, self.message("user", "child-task", "CHILD_TASK", "child-turn")],
            thread="child",
            turn="child-turn",
            fixture=resumed,
        )
        projector = self.store.projection("thread@thread-root")
        root_row = "resumed:request:root-resumed"
        before = projector.page()
        self.assertEqual(before["rowIds"], [root_row])
        cached = projector.detail(root_row, "input:0")
        self.assertEqual(cached["inputDetail"], "ROOT_AFTER_RESUME")
        self.request("parent", [inherited])
        after = projector.page()
        self.assertEqual(after["rowIds"], ["trace-test:request:parent", root_row])
        fresh = projector.detail(root_row, "input:0")
        self.assertEqual(fresh["recordId"], cached["recordId"])
        self.assertEqual(fresh["inputDetail"], cached["inputDetail"])
        self.assertGreater(fresh["seq"], cached["seq"])
        self.assertGreater(fresh["turn"], cached["turn"])
        root_number = next(item for item in after["requestNumbers"] if item["rowId"] == root_row)
        self.assertEqual(fresh["seq"], root_number["seq"])
        self.assertEqual(
            {row["threadId"] for row in projector.index.rows.values()}, {"thread-root"}
        )
        self.assertEqual(set(projector.index.turns), {"main-turn", "resumed-root-turn"})
        self.assertEqual(projector.index.threads, {"thread-root": "/root"})
        texts = [cell.get("previewMarkdown") for cell in after["cells"]]
        self.assertEqual(texts.count("OLDER_PARENT_DISCOVERED_LATER"), 1)
        self.assertEqual(texts.count("ROOT_AFTER_RESUME"), 1)
        self.assertNotIn("CHILD_TASK", texts)
        with self.assertRaises(TraceError) as missing:
            self.input_cells(projector, "resumed:request:child")
        self.assertEqual(missing.exception.code, "record_not_found")

    def test_warm_metadata_append_does_not_reread_old_request_bodies(self):
        inherited = self.message("user", "parent-user", "PARENT_INPUT", "main-turn")
        self.request("parent", [inherited])
        self.thread("child", "/root/review")
        self.request(
            "child",
            [inherited, self.message("user", "own", "CHILD_TASK", "child-turn")],
            thread="child",
            turn="child-turn",
        )
        projector = self.projection()
        projector.page()
        before = projector.index.metrics["payloadReads"]
        self.append(
            "codex_turn_started", thread="child", thread_id="child", codex_turn_id="next-child-turn"
        )
        projector.page(row_ids=["request:child"])
        self.assertEqual(projector.index.metrics["payloadReads"], before)

    def test_late_agent_path_rebuilds_a_cached_first_fork_snapshot(self):
        inherited = self.message("user", "parent-user", "PARENT_INPUT", "main-turn")
        self.request("parent", [inherited])
        self.thread("child", "unknown-path")
        self.request(
            "child",
            [inherited, self.message("user", "own", "CHILD_TASK", "child-turn")],
            thread="child",
            turn="child-turn",
        )
        projector = self.projection()
        before = projector.page(row_ids=["request:child"])
        self.assertEqual(
            [cell["previewMarkdown"] for cell in before["cells"] if cell["kind"] == "user"],
            ["PARENT_INPUT", "CHILD_TASK"],
        )
        epoch = projector.index.epoch
        revision = projector.index.overview()["revision"]
        self.thread("child", "/root/review")
        self.assertTrue(projector.index.delta(revision)["resync"])
        after = projector.page(row_ids=["request:child"])
        self.assertEqual(projector.index.epoch, epoch)
        self.assertEqual(
            [cell["previewMarkdown"] for cell in after["cells"] if cell["kind"] == "user"],
            ["CHILD_TASK"],
        )


if __name__ == "__main__":
    unittest.main()
