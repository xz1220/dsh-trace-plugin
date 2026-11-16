"""Behavior checks for the real Codex → upstream DSH adapter."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/codex-dsh-trace/server"))

from fixtures import Fixture
from projection_fixture import ProjectionFixture
from store import TraceError


class ProjectionTests(ProjectionFixture, unittest.TestCase):
    def test_turns_steps_and_request_result_anchor(self):
        self.fixture.conversation()
        page = self.project().page()
        self.assertEqual(
            [cell["kind"] for cell in page["cells"]],
            ["system", "user", "message", "tool", "subtool", "message"],
        )
        self.assertEqual([request["step"] for request in page["requestNumbers"]], [1, 2])
        first = page["requestNumbers"][0]
        matches = [cell for cell in page["cells"] if cell.get("sourceSeq") == first["resultSeq"]]
        self.assertEqual([cell["kind"] for cell in matches], ["message"])
        self.assertTrue(all(cell["detailsPending"] for cell in page["cells"]))
        self.assertEqual(self.project().index.overview()["codeCellCount"], 1)
        self.assertNotIn("Controlled prompt", json.dumps(page))

    def test_token_buckets_and_cumulative_usage_do_not_double_count_cache(self):
        self.fixture.conversation()
        row = self.project().index.get_row("request:first")
        ref = self.fixture.payload(
            {
                "output_items": [],
                "token_usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 30,
                    "cache_write_input_tokens": 10,
                    "output_tokens": 20,
                    "reasoning_output_tokens": 5,
                },
            },
            "inference_response",
        )
        self.fixture.append(
            "inference_completed",
            inference_call_id="first",
            response_id="resp-first",
            response_payload=ref,
        )
        projector = self.project()
        row = projector.index.get_row("request:first")
        info = projector.request_info(row, True)
        self.assertEqual(
            info["usage"],
            {"input": 60, "cacheRead": 30, "cacheWrite": 10, "output": 20, "reasoning": 5},
        )
        self.assertEqual(info["usage"], info["cumulativeUsage"])

    def test_request_numbers_and_steps_survive_cross_agent_append(self):
        request = self.fixture.payload({"input": []}, "inference_request")
        for thread, turn, name in [
            ("thread-root", "root-turn", "root-first"),
            ("thread-child", "child-turn", "child-first"),
        ]:
            self.fixture.append("codex_turn_started", thread_id=thread, codex_turn_id=turn)
            self.fixture.append(
                "inference_started",
                inference_call_id=name,
                thread_id=thread,
                codex_turn_id=turn,
                model="test",
                request_payload=request,
            )
        projector = self.project()
        before = projector.page()
        self.assertEqual([q["step"] for q in before["requestNumbers"]], [1, 1])
        self.fixture.append(
            "inference_started",
            inference_call_id="root-second",
            thread_id="thread-root",
            codex_turn_id="root-turn",
            model="test",
            request_payload=request,
        )
        after = projector.page()
        self.assertEqual([q["number"] for q in after["requestNumbers"]], [1, 2, 3])
        self.assertEqual([q["step"] for q in after["requestNumbers"]], [1, 1, 2])
        self.assertEqual([q["turn"] for q in after["requestNumbers"]], [1, 2, 1])

    def test_search_reads_body_beyond_summary_and_schema(self):
        self.fixture.conversation("start " + ("x" * 5000) + " UNIQUE_DEEP_BODY")
        projector = self.project()
        page = projector.page()
        self.assertNotIn("UNIQUE_DEEP_BODY", json.dumps(page))
        found = projector.search("unique_deep_body", page["rowIds"])
        self.assertIn("request:first:prompt", found)

    def test_search_includes_the_displayed_locale_group_labels(self):
        self.fixture.conversation()
        projector = self.project()
        page = projector.page()
        expected = {cell["recordId"] for cell in page["cells"] if not cell.get("requestOnly")}
        self.assertEqual(projector.search("step", page["rowIds"]), [])
        self.assertEqual(set(projector.search("step", page["rowIds"], "en")), expected)
        self.assertEqual(set(projector.search("ステップ", page["rowIds"], "ja")), expected)

    def test_search_excludes_hidden_row_flags_but_keeps_actual_boolean_values(self):
        self.fixture.conversation()
        projector = self.project()
        page = projector.page()
        self.assertEqual(projector.search("false", page["rowIds"]), [])
        result = self.fixture.payload({"value": False, "label": "actual boolean"}, "tool_result")
        self.fixture.append(
            "tool_call_ended", tool_call_id="tool-one", status="completed", result_payload=result
        )
        projector = self.project()
        page = projector.page()
        self.assertEqual(projector.search("false", page["rowIds"]), ["tool:tool-one:tool"])

    def test_completed_record_refreshes_existing_metadata_and_detail(self):
        self.fixture.conversation()
        projector = self.project()
        before = projector.page()
        self.assertIsNone(before["cells"][-1]["timeSeconds"])
        response = self.fixture.payload(
            {
                "output_items": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "new final value"}],
                    }
                ]
            },
            "inference_response",
        )
        self.fixture.append(
            "inference_completed",
            inference_call_id="second",
            response_id="resp-two",
            response_payload=response,
        )
        after = self.store.projection("trace-test").page(row_ids=["request:second"])
        self.assertEqual(after["cells"][0]["previewMarkdown"], "new final value")
        self.assertIsNotNone(after["cells"][0]["timeSeconds"])
        self.assertEqual(
            projector.detail("request:second", "assistant")["outputDetail"], "new final value"
        )

    def test_request_pages_and_direct_missing_record(self):
        self.fixture.conversation()
        projector = self.project()
        page = projector.page(limit=2)
        self.assertTrue(page["hasEarlier"])
        earlier = projector.page(limit=2, before=page["beforeSeq"])
        self.assertFalse(set(page["rowIds"]) & set(earlier["rowIds"]))
        with self.assertRaises(TraceError):
            projector.detail("request:first", "not-a-cell")

    def test_native_root_preserves_both_recordings_after_resume(self):
        self.fixture.conversation()
        self.assertEqual(
            self.store.open(thread_id="thread-root")["trace"]["id"], "thread@thread-root"
        )
        later = Fixture(self.root / "later", started_at=2000)
        path = later.root / "manifest.json"
        meta = json.loads(path.read_text())
        meta.update(trace_id="trace-later", started_at_unix_ms=2000)
        path.write_text(json.dumps(meta))
        self.store.catalog.register(str(later.root))
        self.assertEqual(self.store.open(thread_id="thread-root")["requestCount"], 2)
        self.assertEqual(self.store.open(trace_id="trace-later")["rows"], [])
        later.conversation()
        aggregate = self.store.open(thread_id="thread-root")
        self.assertEqual(aggregate["trace"]["id"], "thread@thread-root")
        self.assertEqual(aggregate["requestCount"], 4)
        self.assertEqual(aggregate["trace"]["recordingCount"], 2)
        self.assertEqual(self.store.open(thread_id="unrelated-root")["view"], "select")

    def test_live_binding_uses_exact_root_and_returns_only_metadata(self):
        self.fixture.conversation()
        resolved = self.store.binding("thread-root")
        self.assertEqual(set(resolved), {"currentThreadId", "trace"})
        self.assertEqual(resolved["trace"]["id"], "thread@thread-root")
        self.assertNotIn("_path", resolved["trace"])
        self.assertEqual(self.store.index("trace-test").metrics["payloadReads"], 0)
        self.assertIsNone(self.store.binding("unrelated-root")["trace"])

    def test_restarted_empty_recording_preserves_history_until_first_new_request(self):
        self.fixture.conversation()
        later = Fixture(self.root / "resumed", started_at=3000)
        manifest = later.root / "manifest.json"
        meta = json.loads(manifest.read_text())
        meta.update(trace_id="trace-resumed", started_at_unix_ms=3000)
        manifest.write_text(json.dumps(meta))
        self.store.catalog.register(str(later.root))
        later.append("rollout_started", trace_id="trace-resumed", root_thread_id="thread-root")
        later.append("thread_started", thread_id="thread-root", agent_path="/root")
        self.assertEqual(self.store.binding("thread-root")["trace"]["id"], "thread@thread-root")
        self.assertEqual(self.store.open(thread_id="thread-root")["requestCount"], 2)
        request = later.payload(
            {
                "input": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "New turn after resume"}],
                    }
                ]
            },
            "inference_request",
        )
        later.append(
            "inference_started",
            inference_call_id="resumed-first",
            thread_id="thread-root",
            request_payload=request,
        )
        self.assertEqual(self.store.binding("thread-root")["trace"]["id"], "thread@thread-root")
        self.assertEqual(self.store.open(thread_id="thread-root")["requestCount"], 3)

    def test_explicit_trace_cannot_silently_bind_a_different_root(self):
        self.fixture.conversation()
        with self.assertRaisesRegex(TraceError, "录制与聊天标识不一致"):
            self.store.open(trace_id="trace-test", thread_id="unrelated-root")

    def test_compaction_is_grouped_between_turns_with_recorded_model(self):
        request = self.fixture.payload(
            {"input": [], "model": "compact-model"}, "compaction_request"
        )
        self.fixture.append(
            "compaction_request_started",
            compaction_id="compact",
            compaction_request_id="attempt",
            thread_id="thread-root",
            codex_turn_id=None,
            model="compact-model",
            provider_name="recorded-provider",
            request_payload=request,
        )
        result = self.fixture.payload(
            {"output_items": [{"type": "compaction", "encrypted_content": "opaque"}]},
            "compaction_response",
        )
        self.fixture.append(
            "compaction_request_completed",
            compaction_id="compact",
            compaction_request_id="attempt",
            response_payload=result,
        )
        page = self.project().page()
        self.assertIsNone(page["cells"][0]["turn"])
        self.assertEqual(page["cells"][0]["kind"], "compacted")
        self.assertEqual(page["requestNumbers"][0]["purpose"], "compaction")
        self.assertEqual(page["requestNumbers"][0]["provider"], "recorded-provider")
        self.assertEqual(self.project().index.overview()["requestCount"], 1)

    def test_unrelated_events_reuse_a_completed_detail(self):
        self.fixture.conversation()
        projector = self.project()
        selected = projector.detail("request:first", "assistant")
        self.fixture.append("tool_call_runtime_started", tool_call_id="tool-one")
        self.assertIs(projector.detail("request:first", "assistant"), selected)

    def test_paging_never_combines_different_live_versions(self):
        self.fixture.conversation()
        metadata = self.store.cell_detail("trace-test", "request:second", "assistant")
        old_version = metadata["cell"]["version"]
        partial = self.fixture.payload(
            {
                "output_items": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "changed during read"}],
                    }
                ]
            },
            "inference_response",
        )
        self.fixture.append(
            "inference_completed",
            inference_call_id="second",
            response_id="response-two",
            response_payload=partial,
        )
        with self.assertRaisesRegex(TraceError, "记录已更新"):
            self.store.cell_text(
                "trace-test", "request:second", "assistant", "outputDetail", 0, old_version
            )


if __name__ == "__main__":
    unittest.main()
