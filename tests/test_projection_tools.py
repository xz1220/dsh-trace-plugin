"""Behavior checks for the real Codex → upstream DSH adapter."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/codex-dsh-trace/server"))

from fixtures import Fixture
from projection_fixture import ProjectionFixture
from store import TraceError


class ProjectionToolTests(ProjectionFixture, unittest.TestCase):
    def test_tool_parent_references_are_available_without_assistant_hydration(self):
        self.fixture.conversation()
        page = self.project().page()
        assistant = next(
            cell for cell in page["cells"] if cell["recordId"] == "request:first:assistant"
        )
        calls = [block for block in assistant["sourceBlocks"] if block["type"] == "tool-call"]
        self.assertEqual([block["callId"] for block in calls], ["call-1"])
        self.assertTrue(assistant["detailsPending"])
        self.assertTrue(all(block["content"] == "" for block in calls))
        self.assertNotIn("read()", json.dumps(assistant))

    def test_call_lookup_uses_recorded_identity_without_reading_bodies(self):
        self.fixture.conversation()
        index = self.store.index("trace-test")
        index.overview()
        reads = index.metrics["payloadReads"]
        self.assertEqual(self.store.locate_call("trace-test", "call-1")["id"], "cell:thread-root:1")
        self.assertEqual(
            self.store.locate_call("trace-test", "cell:thread-root:1")["callId"], "call-1"
        )
        self.assertEqual(self.store.locate_call("trace-test", "tool-one")["id"], "tool:tool-one")
        self.assertEqual(index.metrics["payloadReads"], reads)
        with self.assertRaises(TraceError):
            self.store.locate_call("trace-test", "missing-call")

    def test_call_launcher_returns_only_metadata_and_locator_rejects_ambiguous_arguments(self):
        import main

        self.fixture.conversation()
        with patch.object(main, "STORE", self.store):
            launched = main.call(
                "show_rollout_trace", {"traceId": "trace-test", "callId": "call-1"}
            )
            self.assertEqual(set(launched), {"view", "trace", "focusCallId"})
            self.assertEqual(launched["focusCallId"], "call-1")
            self.assertEqual(
                main.call("get_rollout_record", {"traceId": "trace-test", "callId": "call-1"})[
                    "row"
                ]["id"],
                "cell:thread-root:1",
            )
            with self.assertRaises(TraceError):
                main.call("get_rollout_record", {"traceId": "trace-test"})
            with self.assertRaises(TraceError):
                main.call(
                    "get_rollout_record",
                    {"traceId": "trace-test", "rowId": "tool:tool-one", "callId": "call-1"},
                )

    def test_program_source_and_tool_arguments_are_not_reformatted(self):
        self.fixture.conversation()
        projector = self.project()
        code = projector.detail("cell:thread-root:1", "tool")
        self.assertEqual(code["programSource"], "read()")
        self.assertEqual(code["programLanguage"], "javascript")
        tool = projector.detail("tool:tool-one", "tool")
        self.assertEqual(tool["inputDetail"], '{"cmd":"cat fixture"}')
        self.assertEqual(tool["outputDetail"], "fixture value\n")

    def test_code_summary_is_available_before_opening_its_details(self):
        self.fixture.conversation()
        original = '{ "code": "console.log(42);\\n", "description": "Describe the program" }'
        ref = self.fixture.payload(
            {"tool_name": "run_code", "payload": {"arguments": original}}, "tool_invocation"
        )
        self.fixture.append(
            "tool_call_started",
            tool_call_id="native-program",
            requester={"type": "model"},
            kind={"type": "other", "name": "run_code"},
            summary={"label": "run_code"},
            invocation_payload=ref,
        )
        projector = self.project()
        cell = projector.page()["cells"][-1]
        self.assertEqual(cell["programDescription"], "Describe the program")
        detail = projector.detail("tool:native-program", "tool")
        self.assertNotIn("programSource", detail)
        self.assertEqual(detail["inputDetail"], original)

    def test_namespaced_tool_schemas_keep_their_identity(self):
        tools = [
            {
                "type": "namespace",
                "name": namespace,
                "tools": [
                    {
                        "type": "function",
                        "name": "echo",
                        "description": namespace,
                        "parameters": {"type": "object"},
                    }
                ],
            }
            for namespace in ("first", "second")
        ]
        request = self.fixture.payload({"input": [], "tools": tools}, "inference_request")
        self.fixture.append(
            "inference_started",
            inference_call_id="namespaces",
            model="test",
            request_payload=request,
        )
        invocation = self.fixture.payload(
            {"tool_namespace": "second", "tool_name": "echo", "payload": {"arguments": "{}"}},
            "tool_invocation",
        )
        self.fixture.append(
            "tool_call_started",
            tool_call_id="echo",
            requester={"type": "model"},
            kind={"type": "other", "name": "echo"},
            summary={"label": "echo"},
            invocation_payload=invocation,
        )
        projector = self.project()
        projector.page()
        tools = projector.prompt(projector.requests()[0])["tools"]
        self.assertEqual([tool["name"] for tool in tools], ["first.echo", "second.echo"])
        schema = json.loads(projector.detail("tool:echo", "tool")["schemaDetail"])
        self.assertEqual(schema["description"], "second")

    def test_latest_in_history_tool_declaration_replaces_its_old_schema(self):
        self.fixture.conversation()

        def declaration(description):
            return {
                "type": "additional_tools",
                "role": "developer",
                "tools": [
                    {
                        "type": "namespace",
                        "name": "service",
                        "tools": [
                            {
                                "type": "function",
                                "name": "echo",
                                "description": description,
                                "parameters": {"type": "object"},
                            }
                        ],
                    }
                ],
            }

        first = self.fixture.root / "payloads/1.json"
        value = json.loads(first.read_text())
        value["input"][0] = declaration("old schema")
        first.write_text(json.dumps(value))
        second = self.fixture.root / "payloads/5.json"
        value = json.loads(second.read_text())
        value["input"].append(declaration("new schema"))
        second.write_text(json.dumps(value))
        projector = self.project()
        projector.page()
        tools = projector.prompt(projector.requests()[-1])["tools"]
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "service.echo")
        self.assertEqual(tools[0]["description"], "new schema")

    @staticmethod
    def recorded_terminal_declaration(marker):
        return (
            "### `exec_command`\n\nRun a terminal command from the recorded runtime.\n\n"
            "exec tool declaration:\n```ts\n"
            "declare const tools: { exec_command(args: {\n"
            f"  // {marker}\n"
            "  cmd: string;\n  workdir?: string;\n"
            "}): Promise<{ exit_code: number }>; };\n```\n"
        )

    @staticmethod
    def recorded_code_mode_catalog(description):
        return {
            "type": "additional_tools",
            "role": "developer",
            "tools": [
                {
                    "type": "namespace",
                    "name": "functions",
                    "tools": [
                        {
                            "type": "custom",
                            "name": "exec",
                            "description": description,
                            "format": {"type": "text"},
                        }
                    ],
                }
            ],
        }

    def set_recorded_code_mode_catalog(self, description, fixture=None):
        fixture = fixture or self.fixture
        path = fixture.root / "payloads/1.json"
        raw = json.loads(path.read_text())
        raw["input"][0] = self.recorded_code_mode_catalog(description)
        path.write_text(json.dumps(raw))

    def test_subtool_schema_uses_its_recorded_typescript_declaration_without_expanding_catalog(
        self,
    ):
        self.fixture.conversation()
        declaration = self.recorded_terminal_declaration("RECORDED_TERMINAL_SIGNATURE")
        self.set_recorded_code_mode_catalog(declaration)
        projector = self.project()
        page = projector.page()
        detail = projector.detail("tool:tool-one", "tool")
        self.assertEqual(detail["kind"], "subtool")
        self.assertIn("RECORDED_TERMINAL_SIGNATURE", detail["schemaDetail"])
        self.assertIn("cmd: string;", detail["schemaDetail"])
        self.assertIn("declare const tools: { exec_command(", detail["schemaDetail"])
        self.assertEqual(
            [tool["name"] for tool in projector.prompt(projector.requests()[0])["tools"]],
            ["functions.exec"],
        )
        self.assertNotIn("RECORDED_TERMINAL_SIGNATURE", json.dumps(page))

    def test_subtool_recorded_json_schema_takes_priority_over_typescript_documentation(self):
        self.fixture.conversation()
        self.set_recorded_code_mode_catalog(
            self.recorded_terminal_declaration("TYPESCRIPT_FALLBACK")
        )
        path = self.fixture.root / "payloads/1.json"
        raw = json.loads(path.read_text())
        parameters = {
            "type": "object",
            "properties": {"cmd": {"type": "string"}},
            "required": ["cmd"],
        }
        raw["tools"] = [
            {
                "type": "function",
                "name": "exec_command",
                "description": "RECORDED_JSON_SCHEMA",
                "parameters": parameters,
            }
        ]
        path.write_text(json.dumps(raw))
        schema = json.loads(self.project().detail("tool:tool-one", "tool")["schemaDetail"])
        self.assertEqual(schema["description"], "RECORDED_JSON_SCHEMA")
        self.assertEqual(schema["parameters"], parameters)
        self.assertNotIn("TYPESCRIPT_FALLBACK", json.dumps(schema))

    def test_subtool_without_recorded_declaration_keeps_schema_unavailable(self):
        self.fixture.conversation()
        self.assertFalse(self.project().detail("tool:tool-one", "tool")["schemaDetail"])

    def test_subtool_conflicting_recorded_declarations_are_not_guessed(self):
        self.fixture.conversation()
        self.set_recorded_code_mode_catalog(
            self.recorded_terminal_declaration("FIRST_SIGNATURE")
            + "\n"
            + self.recorded_terminal_declaration("CONFLICTING_SIGNATURE")
        )
        self.assertFalse(self.project().detail("tool:tool-one", "tool")["schemaDetail"])

    def test_subtool_truncated_recorded_declaration_is_not_presented_as_schema(self):
        self.fixture.conversation()
        declaration = self.recorded_terminal_declaration("TRUNCATED_SIGNATURE").rsplit("```", 1)[0]
        self.set_recorded_code_mode_catalog(declaration)
        self.assertFalse(self.project().detail("tool:tool-one", "tool")["schemaDetail"])

    def test_subtool_does_not_match_an_unrelated_namespace_signature(self):
        self.fixture.conversation()
        self.set_recorded_code_mode_catalog(
            self.recorded_terminal_declaration("UNQUALIFIED_SIGNATURE")
        )
        path = self.fixture.root / "payloads/3.json"
        raw = json.loads(path.read_text())
        raw["tool_namespace"] = "unrelated"
        path.write_text(json.dumps(raw))
        self.assertFalse(self.project().detail("tool:tool-one", "tool")["schemaDetail"])

    def test_model_tool_does_not_borrow_a_code_mode_subtool_signature(self):
        self.fixture.conversation()
        self.set_recorded_code_mode_catalog(
            self.recorded_terminal_declaration("SUBTOOL_ONLY_SIGNATURE")
        )
        path = self.fixture.root / "trace.jsonl"
        events = [json.loads(line) for line in path.read_text().splitlines()]
        for event in events:
            if event["payload"]["type"] == "tool_call_started":
                event["payload"]["requester"] = {"type": "model"}
        path.write_text("".join(json.dumps(event) + "\n" for event in events))
        self.assertFalse(self.project().detail("tool:tool-one", "tool")["schemaDetail"])

    def append_second_recorded_subtool(self, description):
        path = self.fixture.root / "payloads/5.json"
        raw = json.loads(path.read_text())
        raw["input"].append(self.recorded_code_mode_catalog(description))
        path.write_text(json.dumps(raw))
        self.fixture.append(
            "code_cell_started",
            runtime_cell_id="2",
            model_visible_call_id="call-2",
            source_js="second()",
        )
        invocation = self.fixture.payload(
            {
                "tool_name": "exec_command",
                "payload": {"type": "function", "arguments": '{"cmd":"second"}'},
            },
            "tool_invocation",
        )
        self.fixture.append(
            "tool_call_started",
            tool_call_id="tool-two",
            requester={"type": "code_cell", "runtime_cell_id": "2"},
            kind={"type": "exec_command"},
            summary={"label": "exec_command"},
            invocation_payload=invocation,
        )

    def test_subtool_schema_uses_the_latest_declaration_at_its_own_parent_request(self):
        self.fixture.conversation()
        self.set_recorded_code_mode_catalog(self.recorded_terminal_declaration("EARLIER_SIGNATURE"))
        self.append_second_recorded_subtool(self.recorded_terminal_declaration("UPDATED_SIGNATURE"))
        projector = self.project()
        earlier = projector.detail("tool:tool-one", "tool")["schemaDetail"]
        updated = projector.detail("tool:tool-two", "tool")["schemaDetail"]
        self.assertIn("EARLIER_SIGNATURE", earlier)
        self.assertNotIn("UPDATED_SIGNATURE", earlier)
        self.assertIn("UPDATED_SIGNATURE", updated)
        self.assertNotIn("EARLIER_SIGNATURE", updated)

    def test_subtool_schema_never_borrows_a_declaration_from_a_future_request(self):
        self.fixture.conversation()
        self.append_second_recorded_subtool(self.recorded_terminal_declaration("FUTURE_SIGNATURE"))
        projector = self.project()
        self.assertFalse(projector.detail("tool:tool-one", "tool")["schemaDetail"])
        self.assertIn("FUTURE_SIGNATURE", projector.detail("tool:tool-two", "tool")["schemaDetail"])

    def test_same_named_subtools_keep_schema_provenance_across_recordings(self):
        self.fixture.conversation()
        self.set_recorded_code_mode_catalog(
            self.recorded_terminal_declaration("FIRST_RECORDING_SIGNATURE")
        )
        second = Fixture(self.root / "resumed", schema_version=2, started_at=10000)
        second.conversation()
        path = second.root / "manifest.json"
        meta = json.loads(path.read_text())
        meta["trace_id"] = "trace-resumed"
        path.write_text(json.dumps(meta))
        self.set_recorded_code_mode_catalog(
            self.recorded_terminal_declaration("RESUMED_RECORDING_SIGNATURE"), fixture=second
        )
        self.store.catalog.register(str(second.root))
        projector = self.store.projection("thread@thread-root")
        first = projector.detail("trace-test:tool:tool-one", "tool")["schemaDetail"]
        resumed = projector.detail("trace-resumed:tool:tool-one", "tool")["schemaDetail"]
        self.assertIn("FIRST_RECORDING_SIGNATURE", first)
        self.assertNotIn("RESUMED_RECORDING_SIGNATURE", first)
        self.assertIn("RESUMED_RECORDING_SIGNATURE", resumed)
        self.assertNotIn("FIRST_RECORDING_SIGNATURE", resumed)


if __name__ == "__main__":
    unittest.main()
