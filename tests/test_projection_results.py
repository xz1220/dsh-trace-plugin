"""Behavior checks for the real Codex → upstream DSH adapter."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/codex-dsh-trace/server"))

from projection_fixture import ProjectionFixture


class ProjectionResultTests(ProjectionFixture, unittest.TestCase):
    def test_empty_failed_request_has_no_fabricated_assistant_result_link(self):
        self.fixture.conversation()
        self.fixture.append(
            "inference_failed",
            inference_call_id="second",
            error="Controlled empty failure",
            partial_response_payload=None,
        )
        page = self.project().page()
        self.assertNotIn("resultSeq", page["requestNumbers"][-1])
        self.assertTrue(page["cells"][-1]["requestOnly"])
        self.assertEqual(page["requestNumbers"][-1]["error"], "Controlled empty failure")

    def test_reasoning_only_is_not_mislabelled_as_a_tool_call(self):
        self.fixture.conversation()
        response = self.fixture.payload(
            {
                "output_items": [
                    {
                        "type": "reasoning",
                        "summary": [{"type": "summary_text", "text": "Public summary"}],
                    }
                ]
            },
            "inference_response",
        )
        self.fixture.append(
            "inference_completed",
            inference_call_id="second",
            response_id="r-two",
            response_payload=response,
        )
        projector = self.project()
        page = projector.page()
        self.assertEqual(page["cells"][-1]["text"], "")
        self.assertEqual(page["cells"][-1]["previewMarkdown"], "Public summary")
        self.assertEqual(
            projector.detail("request:second", "assistant")["thinkingDetail"], "Public summary"
        )
        opaque = self.fixture.payload(
            {
                "output_items": [
                    {"type": "reasoning", "summary": None, "encrypted_content": "opaque"}
                ]
            },
            "inference_response",
        )
        self.fixture.append(
            "inference_completed",
            inference_call_id="second",
            response_id="r-two",
            response_payload=opaque,
        )
        page = self.project().page()
        self.assertNotIn("resultSeq", page["requestNumbers"][-1])
        self.assertNotIn("仅工具调用", page["cells"][-1]["text"])

    def test_assistant_image_only_has_a_bounded_caption_and_full_image_detail(self):
        self.fixture.conversation()
        image = "data:image/png;base64,aGVsbG8="
        response = self.fixture.payload(
            {
                "output_items": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "input_image", "image_url": image}],
                    }
                ]
            },
            "inference_response",
        )
        self.fixture.append(
            "inference_completed",
            inference_call_id="second",
            response_id="r-two",
            response_payload=response,
        )
        projector = self.project()
        page = projector.page()
        self.assertEqual(page["cells"][-1]["text"], "图片 ×1")
        self.assertNotIn(image, json.dumps(page))
        detail = projector.detail("request:second", "assistant")
        self.assertEqual(detail["sourceBlocks"][0]["attachment"]["recordedUrl"], image)

    def test_images_files_and_original_block_order(self):
        image = "data:image/png;base64,aGVsbG8="
        request = self.fixture.payload(
            {
                "input": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "before"},
                            {"type": "input_image", "image_url": image, "width": 10, "height": 20},
                            {
                                "type": "input_file",
                                "filename": "empty.txt",
                                "size": 0,
                                "mime_type": "text/plain",
                            },
                            {"type": "input_text", "text": "after"},
                        ],
                    }
                ]
            },
            "inference_request",
        )
        self.fixture.append(
            "inference_started",
            inference_call_id="attachments",
            model="test",
            request_payload=request,
        )
        projector = self.project()
        page = projector.page()
        self.assertNotIn(image, json.dumps(page))
        cell = projector.detail("request:attachments", "input:0")
        self.assertEqual(cell["inputDetail"], "before\n\nafter")
        self.assertEqual(
            [block["type"] for block in cell["sourceBlocks"]], ["text", "image", "file", "text"]
        )
        self.assertEqual(cell["sourceBlocks"][1]["attachment"]["recordedUrl"], image)
        self.assertEqual(cell["sourceBlocks"][2]["file"]["bytes"], 0)

    def test_failed_and_cancelled_partial_outputs_remain_inspectable(self):
        self.fixture.conversation()
        partial = self.fixture.payload(
            {
                "output_items": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "partial output"}],
                    }
                ]
            },
            "inference_response",
        )
        self.fixture.append(
            "inference_cancelled",
            inference_call_id="second",
            reason="user cancelled",
            partial_response_payload=partial,
        )
        projector = self.project()
        page = projector.page()
        self.assertTrue(page["cells"][-1]["isError"])
        self.assertEqual(
            projector.detail("request:second", "assistant")["outputDetail"], "partial output"
        )
        self.assertEqual(page["requestNumbers"][-1]["error"], "user cancelled")

    def test_json_null_result_is_available_and_not_missing(self):
        self.fixture.conversation()
        result = self.fixture.payload(None, "tool_result")
        self.fixture.append(
            "tool_call_ended", tool_call_id="tool-one", status="completed", result_payload=result
        )
        value = self.store.text("trace-test", "tool:tool-one", "raw_result")
        self.assertTrue(value["available"])
        self.assertEqual(value["text"], "null")

    def test_business_value_field_is_not_a_result_envelope(self):
        self.fixture.conversation()
        expected = {"value": 42, "label": "retain this field"}
        result = self.fixture.payload(expected, "tool_result")
        self.fixture.append(
            "tool_call_ended", tool_call_id="tool-one", status="completed", result_payload=result
        )
        self.assertEqual(
            json.loads(self.store.text("trace-test", "tool:tool-one", "result")["text"]), expected
        )
        self.assertEqual(
            json.loads(self.project().detail("tool:tool-one", "tool")["outputDetail"]), expected
        )

    def test_tool_images_and_error_text_keep_their_recorded_order(self):
        self.fixture.conversation()
        image = "data:image/png;base64,aGVsbG8="
        raw = {
            "isError": True,
            "content": [
                {"type": "text", "text": " \n"},
                {"type": "image", "mimeType": "image/png", "data": "aGVsbG8="},
            ],
        }
        result = self.fixture.payload(raw, "tool_result")
        self.fixture.append(
            "tool_call_ended", tool_call_id="tool-one", status="completed", result_payload=result
        )
        projector = self.project()
        page = projector.page()
        self.assertNotIn(image, json.dumps(page))
        cell = projector.detail("tool:tool-one", "tool")
        self.assertTrue(cell["isError"])
        self.assertEqual(cell["outputDetail"], " \n")
        self.assertEqual([block["type"] for block in cell["outputBlocks"]], ["text", "image"])
        self.assertEqual(cell["outputBlocks"][1]["attachment"]["recordedUrl"], image)

    def test_code_cell_text_and_images_use_the_recorded_content_items(self):
        self.fixture.conversation()
        raw = {
            "response": {
                "Result": {
                    "cell_id": "1",
                    "content_items": [
                        {"type": "input_text", "text": "console line\n"},
                        {"type": "input_image", "image_url": "data:image/png;base64,aGVsbG8="},
                    ],
                    "error_text": None,
                }
            }
        }
        result = self.fixture.payload(raw, "tool_result")
        self.fixture.append(
            "code_cell_ended", runtime_cell_id="1", status="completed", response_payload=result
        )
        cell = self.project().detail("cell:thread-root:1", "tool")
        self.assertEqual(cell["outputDetail"], "console line\n")
        self.assertEqual([block["type"] for block in cell["outputBlocks"]], ["text", "image"])

    def test_large_structured_result_only_sends_a_bounded_ledger_preview(self):
        self.fixture.conversation()
        result = self.fixture.payload(
            {"value": "x" * 1000000, "label": "complete JSON stays in details"}, "tool_result"
        )
        self.fixture.append(
            "tool_call_ended", tool_call_id="tool-one", status="completed", result_payload=result
        )
        page = self.project().page()
        self.assertLess(len(json.dumps(page)), 20000)
        detail = self.project().detail("tool:tool-one", "tool")
        self.assertEqual(len(json.loads(detail["outputDetail"])["value"]), 1000000)


if __name__ == "__main__":
    unittest.main()
