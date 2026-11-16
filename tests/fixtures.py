"""Small synthetic official recordings shared by tests and local benchmarks."""

import json


class Fixture:
    def __init__(self, root, schema_version=1, started_at=1000):
        self.root = root
        self.schema_version = schema_version
        self.started_at = started_at
        (root / "payloads").mkdir(parents=True)
        (root / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": schema_version,
                    "trace_id": "trace-test",
                    "rollout_id": "rollout-test",
                    "root_thread_id": "thread-root",
                    "started_at_unix_ms": started_at,
                    "raw_event_log": "trace.jsonl",
                    "payloads_dir": "payloads",
                }
            )
        )
        (root / "trace.jsonl").touch()
        self.seq = 0
        self.payloads = 0

    def payload(self, data, kind):
        self.payloads += 1
        name = f"payloads/{self.payloads}.json"
        (self.root / name).write_text(json.dumps(data, ensure_ascii=False))
        return {
            "raw_payload_id": f"raw_payload:{self.payloads}",
            "kind": {"type": kind},
            "path": name,
        }

    def event(self, record_type, **values):
        self.seq += 1
        return {
            "schema_version": self.schema_version,
            "seq": self.seq,
            "wall_time_unix_ms": self.started_at + self.seq * 10,
            "rollout_id": "rollout-test",
            "thread_id": "thread-root",
            "codex_turn_id": "turn-1",
            "payload": {"type": record_type, **values},
        }

    def append(self, record_type, **values):
        event = self.event(record_type, **values)
        with (self.root / "trace.jsonl").open("a") as f:
            f.write(json.dumps(event) + "\n")
        return event

    def conversation(self, text="Controlled prompt 🌱"):
        self.append("rollout_started", trace_id="trace-test", root_thread_id="thread-root")
        self.append(
            "thread_started", thread_id="thread-root", agent_path="/root", metadata_payload=None
        )
        self.append("codex_turn_started", thread_id="thread-root", codex_turn_id="turn-1")
        req = self.payload(
            {
                "model": "test",
                "input": [
                    {"type": "additional_tools", "role": "developer", "tools": []},
                    {
                        "type": "message",
                        "role": "developer",
                        "content": [{"type": "input_text", "text": text}],
                    },
                    {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "Read fixture"}],
                    },
                ],
            },
            "inference_request",
        )
        self.append(
            "inference_started",
            inference_call_id="first",
            thread_id="thread-root",
            codex_turn_id="turn-1",
            model="test",
            request_payload=req,
        )
        response = self.payload(
            {
                "response_id": "resp-first",
                "output_items": [
                    {
                        "type": "custom_tool_call",
                        "name": "exec",
                        "input": "read()",
                        "call_id": "call-1",
                    }
                ],
                "token_usage": {"input_tokens": 10},
            },
            "inference_response",
        )
        self.append(
            "inference_completed",
            inference_call_id="first",
            response_id="resp-first",
            response_payload=response,
        )
        self.append(
            "code_cell_started",
            runtime_cell_id="1",
            model_visible_call_id="call-1",
            source_js="read()",
        )
        invocation = self.payload(
            {
                "tool_name": "exec_command",
                "payload": {"type": "function", "arguments": '{"cmd":"cat fixture"}'},
            },
            "tool_invocation",
        )
        self.append(
            "tool_call_started",
            tool_call_id="tool-one",
            requester={"type": "code_cell", "runtime_cell_id": "1"},
            kind={"type": "exec_command"},
            summary={"label": "exec_command"},
            invocation_payload=invocation,
        )
        output = self.payload(
            {"type": "code_mode_response", "value": {"output": "fixture value\n", "exit_code": 0}},
            "tool_result",
        )
        self.append(
            "tool_call_ended", tool_call_id="tool-one", status="completed", result_payload=output
        )
        self.append(
            "code_cell_ended", runtime_cell_id="1", status="completed", response_payload=output
        )
        second = self.payload(
            {
                "type": "response.create",
                "model": "test",
                "previous_response_id": "resp-first",
                "input": [
                    {
                        "type": "custom_tool_call_output",
                        "call_id": "call-1",
                        "output": "fixture value\n",
                    }
                ],
            },
            "inference_request",
        )
        self.append(
            "inference_started",
            inference_call_id="second",
            thread_id="thread-root",
            codex_turn_id="turn-1",
            model="test",
            request_payload=second,
        )
