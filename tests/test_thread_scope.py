"""Current-chat aggregation excludes independent child threads in the same capture."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/codex-dsh-trace/server"))

import main
from fixtures import Fixture
from store import Store, TraceError


class CurrentThreadScopeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        isolated = patch.dict(
            os.environ,
            {
                "CODEX_HOME": str(self.root / "codex"),
                "CODEX_ROLLOUT_TRACE_ROOT": str(self.root / "unused"),
            },
        )
        isolated.start()
        self.addCleanup(isolated.stop)
        self.store = Store(self.root / "config.json")
        self.store.catalog.default_root = self.root / "no-default"
        self.fixture = Fixture(self.root / "capture", schema_version=2)
        self.store.catalog.register(str(self.fixture.root))
        self.append("thread_started", thread_id="thread-root", agent_path="/root")
        self.request(
            "main",
            "thread-root",
            "main-turn",
            "MAIN",
            tools=[{"type": "function", "name": "spawn_agent", "parameters": {"type": "object"}}],
        )
        self.response("main", "thread-root", "main-turn", "MAIN_BEFORE_CHILD")
        self.tool("spawn", "spawn_agent", "thread-root", "main-turn", "MAIN_RECEIVED_CHILD_SUMMARY")
        # A child request is recorded before its agent_path metadata arrives.
        self.request(
            "critique",
            "child-thread",
            "child-turn",
            "CHILD_PRIVATE",
            tools=[
                {"type": "function", "name": "child_only_tool", "parameters": {"type": "object"}}
            ],
        )
        self.append(
            "code_cell_started",
            "child-thread",
            "child-turn",
            runtime_cell_id="child-cell",
            source_js="child_private_program()",
        )
        self.tool(
            "child-tool", "exec_command", "child-thread", "child-turn", "CHILD_PRIVATE_STDOUT"
        )
        self.response("critique", "child-thread", "child-turn", "CHILD_PRIVATE_REPLY")
        self.request(
            "main-final", "thread-root", "main-turn", "MAIN_FOLLOWUP", previous="response-main"
        )
        self.response("main-final", "thread-root", "main-turn", "MAIN_FINAL")
        self.identity = "thread@thread-root"
        self.child_rows = [
            "trace-test:request:critique",
            "trace-test:tool:child-tool",
            "trace-test:cell:child-thread:child-cell",
        ]

    def append(self, kind, thread="thread-root", turn="main-turn", **values):
        event = self.fixture.event(kind, **values)
        event.update(thread_id=thread, codex_turn_id=turn)
        with (self.fixture.root / "trace.jsonl").open("a") as stream:
            stream.write(json.dumps(event) + "\n")
        return event

    def request(self, identity, thread, turn, marker, previous=None, tools=None):
        self.append("codex_turn_started", thread, turn, thread_id=thread, codex_turn_id=turn)
        request = {
            "input": [
                {
                    "type": "message",
                    "role": "developer",
                    "content": [{"type": "input_text", "text": marker + "_INSTRUCTIONS"}],
                },
                {
                    "type": "message",
                    "role": "user",
                    "id": marker,
                    "content": [{"type": "input_text", "text": marker + "_QUESTION"}],
                },
            ]
        }
        if previous:
            request["previous_response_id"] = previous
        if tools is not None:
            request["tools"] = tools
        return self.append(
            "inference_started",
            thread,
            turn,
            thread_id=thread,
            codex_turn_id=turn,
            inference_call_id=identity,
            request_payload=self.fixture.payload(request, "inference_request"),
        )

    def response(self, identity, thread, turn, text):
        return self.append(
            "inference_completed",
            thread,
            turn,
            inference_call_id=identity,
            response_id="response-" + identity,
            response_payload=self.fixture.payload(
                {
                    "output_items": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "id": "answer-" + identity,
                            "phase": "final_answer",
                            "content": [{"type": "output_text", "text": text}],
                        }
                    ]
                },
                "inference_response",
            ),
        )

    def tool(self, identity, name, thread, turn, text):
        self.append(
            "tool_call_started",
            thread,
            turn,
            tool_call_id=identity,
            model_visible_call_id="call-" + identity,
            requester={"type": "model"},
            summary={"label": name},
            invocation_payload=self.fixture.payload(
                {"tool_name": name, "payload": {"arguments": json.dumps({"task": "MAIN_TASK"})}},
                "tool_invocation",
            ),
        )
        return self.append(
            "tool_call_ended",
            thread,
            turn,
            tool_call_id=identity,
            status="completed",
            result_payload=self.fixture.payload(
                {"type": "code_mode_response", "value": {"output": text, "exit_code": 0}},
                "tool_result",
            ),
        )

    def call(self, name, **args):
        return main.call(name, args, store=self.store)

    def test_native_aggregate_filters_all_views_and_keeps_main_owned_calls(self):
        log = self.fixture.root / "trace.jsonl"
        original = log.read_bytes()
        opened = main.call("open_rollout_viewer", {}, {"threadId": "thread-root"}, store=self.store)
        self.assertEqual(opened["trace"]["id"], self.identity)
        self.assertEqual(
            self.call("get_rollout_binding", threadId="thread-root")["trace"]["id"], self.identity
        )
        launch = self.call("show_rollout_trace", threadId="thread-root")
        self.assertEqual(launch["trace"]["id"], self.identity)
        self.assertEqual(opened["requestCount"], 2)
        self.assertEqual(
            [row["name"] for row in opened["rows"] if row["type"] == "request"],
            ["请求 #1", "请求 #2"],
        )
        self.assertEqual(opened["toolCount"], 1)
        self.assertEqual(opened["codeCellCount"], 0)
        self.assertEqual([entry["id"] for entry in opened["threads"]], ["thread-root"])
        index = self.store.index(self.identity)
        self.assertEqual(set(index.turns), {"main-turn"})
        self.assertEqual({row["threadId"] for row in opened["rows"]}, {"thread-root"})
        self.assertTrue(all(row["id"] not in self.child_rows for row in opened["rows"]))
        overview = self.call("get_rollout_overview", traceId=self.identity, limit=1)
        self.assertTrue(overview["hasEarlier"])
        earlier = self.call(
            "get_rollout_overview", traceId=self.identity, beforeSeq=overview["beforeSeq"]
        )
        self.assertEqual(len(earlier["rows"]) + len(overview["rows"]), opened["totalRows"])
        page = self.call("get_rollout_projection", traceId=self.identity)
        self.assertNotIn("CHILD_PRIVATE", json.dumps(page))
        self.assertNotIn("child_only_tool", json.dumps(page))
        self.assertEqual({item["turn"] for item in page["requestNumbers"]}, {1})
        self.assertEqual([item["number"] for item in page["requestNumbers"]], [1, 2])
        self.assertTrue(all(cell["threadId"] == "thread-root" for cell in page["cells"]))
        prompt = self.call(
            "get_rollout_cell_detail",
            traceId=self.identity,
            rowId="trace-test:request:main",
            cellKey="prompt",
        )
        prompt_text = self.call(
            "read_rollout_cell_text",
            traceId=self.identity,
            rowId="trace-test:request:main",
            cellKey="prompt",
            field="promptDetail",
            snapshot=prompt["snapshot"],
        )["text"]
        self.assertIn("MAIN_INSTRUCTIONS", prompt_text)
        self.assertIn("spawn_agent", prompt_text)
        self.assertNotIn("CHILD_PRIVATE", prompt_text)
        result = self.call(
            "read_rollout_text",
            traceId=self.identity,
            rowId="trace-test:tool:spawn",
            section="result",
        )
        self.assertEqual(result["text"], "MAIN_RECEIVED_CHILD_SUMMARY")
        self.assertEqual(
            self.call("get_rollout_record", traceId=self.identity, callId="trace-test:call-spawn")[
                "row"
            ]["name"],
            "spawn_agent",
        )
        self.assertEqual(
            self.call(
                "search_rollout_cells",
                traceId=self.identity,
                query="CHILD_PRIVATE",
                rowIds=[row["id"] for row in opened["rows"]],
            )["matches"],
            [],
        )
        # The explicit capture entry remains a complete, multi-thread diagnostic view.
        raw = self.store.open(trace_id="trace-test")
        self.assertEqual(raw["requestCount"], 3)
        self.assertEqual(raw["toolCount"], 2)
        self.assertEqual(raw["codeCellCount"], 1)
        self.assertTrue(any(row["threadId"] == "child-thread" for row in raw["rows"]))
        self.assertEqual(log.read_bytes(), original)

    def test_child_row_locators_details_search_and_context_do_not_escape_scope(self):
        self.store.open(thread_id="thread-root")
        for name, arguments in [
            ("get_rollout_record", {"rowId": self.child_rows[0]}),
            ("get_rollout_record", {"callId": "trace-test:call-child-tool"}),
            ("get_rollout_detail", {"rowId": self.child_rows[0]}),
            ("get_rollout_cell_detail", {"rowId": self.child_rows[0], "cellKey": "prompt"}),
            (
                "read_rollout_cell_text",
                {"rowId": self.child_rows[0], "cellKey": "prompt", "field": "promptDetail"},
            ),
            ("read_rollout_text", {"rowId": self.child_rows[0], "section": "raw_request"}),
            ("get_rollout_request_info", {"rowId": self.child_rows[0]}),
            ("search_rollout_cells", {"query": "CHILD_PRIVATE", "rowIds": self.child_rows}),
        ]:
            with self.subTest(endpoint=name):
                with self.assertRaises(TraceError):
                    self.call(name, traceId=self.identity, **arguments)
        self.assertEqual(
            self.call("get_rollout_projection", traceId=self.identity, rowIds=self.child_rows)[
                "cells"
            ],
            [],
        )
        # An explicit predecessor pointing to a child cannot make its context readable.
        self.request(
            "bad-link", "thread-root", "next-main", "OWN_INPUT", previous="response-critique"
        )
        context = self.store.details(self.identity, "trace-test:request:bad-link")["context"]
        self.assertFalse(context["complete"])
        self.assertEqual(context["missing"], "response-critique")
        text = self.store.text(self.identity, "trace-test:request:bad-link", "full_context")["text"]
        self.assertIn("OWN_INPUT", text)
        self.assertNotIn("CHILD_PRIVATE", text)

    def test_child_append_and_late_metadata_leave_main_delta_and_timeline_unchanged(self):
        opened = self.store.open(thread_id="thread-root")
        projector = self.store.projection(self.identity)
        prior_page = projector.page()
        opened = self.store.index(self.identity).overview()
        revision = opened["revision"]
        reads = self.store.index("trace-test").metrics["payloadReads"]
        self.append(
            "thread_started",
            "child-thread",
            "child-turn",
            thread_id="child-thread",
            agent_path="/root/critique",
        )
        self.request("critique-next", "child-thread", "child-next-turn", "CHILD_PRIVATE_NEXT")
        self.response(
            "critique-next", "child-thread", "child-next-turn", "CHILD_PRIVATE_NEXT_REPLY"
        )
        delta = self.call("get_rollout_delta", traceId=self.identity, revision=revision)
        self.assertTrue(delta["unchanged"])
        self.assertEqual(delta["revision"], revision)
        self.assertEqual(delta["latestTime"], opened["latestTime"])
        self.assertEqual(delta["rows"], [])
        after = self.store.index(self.identity).overview()
        self.assertEqual(after["threads"], opened["threads"])
        self.assertEqual(after["projectionRevision"], opened["projectionRevision"])
        self.assertEqual(after["requestCount"], 2)
        self.assertEqual(projector.page(), prior_page)
        self.assertEqual(self.store.index("trace-test").metrics["payloadReads"], reads)
        self.tool(
            "send", "send_message_to_thread", "thread-root", "main-turn", "MAIN_RECEIVED_FOLLOWUP"
        )
        own_delta = self.call("get_rollout_delta", traceId=self.identity, revision=revision)
        self.assertFalse(own_delta.get("resync", False))
        self.assertEqual([row["id"] for row in own_delta["rows"]], ["trace-test:tool:send"])
        self.assertEqual(
            self.store.text(self.identity, "trace-test:tool:send", "result")["text"],
            "MAIN_RECEIVED_FOLLOWUP",
        )
