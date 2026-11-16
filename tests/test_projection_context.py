"""Behavior checks for the real Codex → upstream DSH adapter."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/codex-dsh-trace/server"))

from projection_fixture import ProjectionFixture
from store import CHUNK


class ProjectionContextTests(ProjectionFixture, unittest.TestCase):
    def greeting_replay(self):
        def message(role, identity, text, turn):
            return {
                "type": "message",
                "role": role,
                "id": identity,
                "internal_chat_message_metadata_passthrough": {"turn_id": turn},
                "content": [
                    {"type": "output_text" if role == "assistant" else "input_text", "text": text}
                ],
            }

        self.fixture.append(
            "codex_turn_started", codex_turn_id="third-turn", thread_id="thread-root"
        )
        inputs = [
            {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": "Instructions"}],
            },
            message(
                "user",
                "environment",
                "<environment_context>test workspace</environment_context>",
                "first-turn",
            ),
            message("user", "hi", "hi", "first-turn"),
            message("assistant", "hi-answer", "Hi!", "first-turn"),
            message("user", "test", "这是测试", "second-turn"),
            message("assistant", "test-answer", "收到，测试正常。", "second-turn"),
            message("user", "continue", "继续测试", "third-turn"),
        ]
        request = self.fixture.payload({"input": inputs}, "inference_request")
        self.fixture.append(
            "inference_started",
            inference_call_id="third",
            thread_id="thread-root",
            codex_turn_id="third-turn",
            request_payload=request,
        )
        response = self.fixture.payload(
            {
                "output_items": [
                    message("assistant", "continue-answer", "好，继续测试中。", "third-turn")
                ]
            },
            "inference_response",
        )
        self.fixture.append(
            "inference_completed", inference_call_id="third", response_payload=response
        )

    def test_resumed_third_turn_restores_recorded_history_turn_numbers(self):
        self.greeting_replay()
        page = self.project().page()
        cells = page["cells"]
        self.assertEqual([cell["turn"] for cell in cells], [None, 1, 1, 1, 2, 2, 3, 3])
        self.assertEqual(page["requestNumbers"][0]["turn"], 3)
        self.assertEqual(
            [cell.get("previewMarkdown") for cell in cells if cell["kind"] in ("user", "message")],
            ["hi", "Hi!", "这是测试", "收到，测试正常。", "继续测试", "好，继续测试中。"],
        )

    def test_history_turn_numbers_stay_stable_when_later_events_arrive(self):
        self.greeting_replay()
        projector = self.project()
        projector.page()
        reads = projector.index.metrics["payloadReads"]
        self.fixture.append(
            "codex_turn_started", codex_turn_id="fourth-turn", thread_id="thread-root"
        )
        self.store.index("trace-test").refresh()
        projector.requests()
        self.assertEqual(
            projector.turn_numbers,
            {"first-turn": 1, "second-turn": 2, "third-turn": 3, "fourth-turn": 4},
        )
        self.assertEqual(projector.index.metrics["payloadReads"], reads)

    def test_replayed_assistant_messages_are_visible_with_request_input_provenance(self):
        history = "## Earlier answer\n\n完整保留 🌱\n"
        inputs = [
            {
                "type": "message",
                "role": "user",
                "id": "old-user",
                "content": [{"type": "input_text", "text": "Earlier question"}],
            },
            {
                "type": "message",
                "role": "assistant",
                "id": "old-assistant",
                "content": [{"type": "output_text", "text": history}],
            },
            {
                "type": "message",
                "role": "user",
                "id": "new-user",
                "content": [{"type": "input_text", "text": "Current question"}],
            },
        ]
        request = self.fixture.payload({"model": "test", "input": inputs}, "inference_request")
        self.fixture.append(
            "inference_started",
            inference_call_id="resumed",
            thread_id="thread-root",
            codex_turn_id="turn-1",
            request_payload=request,
        )
        page = self.project().page()
        cells = page["cells"]
        self.assertEqual([cell["kind"] for cell in cells], ["user", "message", "user", "message"])
        historical = cells[1]
        self.assertTrue(historical["inputHistory"])
        self.assertEqual(historical["step"], 0)
        self.assertNotIn("sourceSeq", historical)
        self.assertFalse(historical["assistantMetrics"]["timingRecorded"])
        self.assertFalse(historical["assistantMetrics"]["usageProvided"])
        self.assertNotIn("output", historical)
        self.assertNotEqual(historical["group"], page["requestNumbers"][0]["group"])
        detail = self.store.cell_detail("trace-test", "request:resumed", "input:1")
        origin = json.loads(
            self.store.cell_text("trace-test", "request:resumed", "input:1", "messageSource")[
                "text"
            ]
        )
        self.assertEqual(origin["role"], "assistant")
        self.assertEqual(origin["origin"], "request_input")
        text = self.store.cell_text("trace-test", "request:resumed", "input:1", "outputDetail")[
            "text"
        ]
        self.assertEqual(text, history)
        self.assertNotIn("inputDetail", detail["fields"])
        self.assertTrue(self.store.projection("trace-test").search("完整保留", ["request:resumed"]))

    def test_full_snapshot_deduplicates_recorded_messages_but_keeps_a_new_identical_user_message(
        self,
    ):
        def message(role, identity, text):
            return {
                "type": "message",
                "role": role,
                "id": identity,
                "content": [
                    {"type": "output_text" if role == "assistant" else "input_text", "text": text}
                ],
            }

        old_user = message("user", "old-user", "Earlier question")
        old_assistant = message("assistant", "old-assistant", "Earlier answer")
        current_user = message("user", "current-user", "Repeat this")
        current_answer = message("assistant", "current-answer", "First recorded answer")
        req = self.fixture.payload(
            {"input": [old_user, old_assistant, current_user]}, "inference_request"
        )
        self.fixture.append(
            "inference_started",
            inference_call_id="one",
            thread_id="thread-root",
            request_payload=req,
        )
        result = self.fixture.payload({"output_items": [current_answer]}, "inference_response")
        self.fixture.append(
            "inference_completed",
            inference_call_id="one",
            response_id="response-one",
            response_payload=result,
        )
        # A transport/context update changes the full prefix, but not message identities.
        req = self.fixture.payload(
            {
                "input": [
                    message("developer", "new-context", "Changed context"),
                    old_user,
                    {
                        **old_assistant,
                        "internal_chat_message_metadata_passthrough": {"turn_id": "old-turn"},
                    },
                    current_user,
                    current_answer,
                    message("user", "different-new-user", "Repeat this"),
                ]
            },
            "inference_request",
        )
        self.fixture.append(
            "inference_started",
            inference_call_id="two",
            thread_id="thread-root",
            request_payload=req,
        )
        cells = self.project().page()["cells"]
        visible = [cell for cell in cells if not cell.get("requestOnly")]
        self.assertEqual(
            sum(cell.get("previewMarkdown") == "Earlier answer" for cell in visible), 1
        )
        self.assertEqual(
            sum(cell.get("previewMarkdown") == "First recorded answer" for cell in visible), 1
        )
        self.assertEqual(sum(cell.get("previewMarkdown") == "Repeat this" for cell in visible), 2)
        later = [
            cell for cell in visible if cell["rowId"] == "request:two" and cell["kind"] == "user"
        ]
        self.assertEqual(len(later), 1)
        self.assertFalse(later[0].get("inputHistory", False))

    def test_failed_current_request_does_not_mark_its_historical_assistant_as_failed(self):
        req = self.fixture.payload(
            {
                "input": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "id": "old",
                        "content": [{"type": "output_text", "text": "Earlier successful answer"}],
                    }
                ]
            },
            "inference_request",
        )
        self.fixture.append(
            "inference_started",
            inference_call_id="failed",
            thread_id="thread-root",
            request_payload=req,
        )
        self.fixture.append(
            "inference_failed", inference_call_id="failed", error="Current request failed"
        )
        historical = next(
            cell for cell in self.project().page()["cells"] if cell.get("inputHistory")
        )
        self.assertFalse(historical["isError"])
        self.assertIsNone(historical["startedAt"])

    def test_prompt_hydration_uses_lossless_unicode_chunks(self):
        expected = "🌱完整上下文\n" * 12000
        self.fixture.conversation(expected)
        projector = self.project()
        projector.page()
        meta = self.store.cell_detail("trace-test", "request:first", "prompt")
        reads = projector.index.metrics["payloadReads"]
        self.assertGreater(meta["fields"]["promptDetail"]["totalChars"], CHUNK)
        offset = 0
        chunks = []
        while offset is not None:
            part = self.store.cell_text(
                "trace-test", "request:first", "prompt", "promptDetail", offset
            )
            chunks.append(part["text"])
            offset = part["nextOffset"]
        prompt = json.loads("".join(chunks))
        self.assertIn(expected, prompt["system"])
        self.assertEqual(projector.index.metrics["payloadReads"], reads)

    def test_long_response_chain_is_iterative_and_preserves_every_item(self):
        previous = None
        for number in range(1100):
            raw = {
                "input": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": str(number)}],
                    }
                ]
            }
            if previous:
                raw["previous_response_id"] = previous
            request = self.fixture.payload(raw, "inference_request")
            self.fixture.append(
                "inference_started",
                inference_call_id=str(number),
                model="test",
                request_payload=request,
            )
            previous = f"response-{number}"
            response = self.fixture.payload(
                {
                    "output_items": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": f"answer-{number}"}],
                        }
                    ]
                },
                "inference_response",
            )
            self.fixture.append(
                "inference_completed",
                inference_call_id=str(number),
                response_id=previous,
                response_payload=response,
            )
        context = self.store.index("trace-test").context("request:1099")
        self.assertTrue(context["complete"])
        self.assertEqual(len(context["items"]), 2199)
        self.assertEqual(context["items"][0]["value"]["content"][0]["text"], "0")
        self.assertEqual(context["items"][-1]["value"]["content"][0]["text"], "1099")


if __name__ == "__main__":
    unittest.main()
