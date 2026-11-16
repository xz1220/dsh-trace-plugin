"""Generate clearly labelled, isolated UI review recordings (no model calls)."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "local-context/review"


class Capture:
    def __init__(self, name, resume=False):
        self.name = name
        self.root = REVIEW / "recordings" / name
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "payloads").mkdir(exist_ok=True)
        self.seq = 0
        self.raw = 0
        self.clock = 1700000000000
        self.thread = "review-root"
        self.turn = "turn-1"
        if resume:
            lines = (self.root / "trace.jsonl").read_text().splitlines()
            last = json.loads(lines[-1])
            self.seq = last["seq"]
            self.clock = last["wall_time_unix_ms"]
            self.raw = max(
                (int(p.stem) for p in (self.root / "payloads").glob("*.json")), default=0
            )
        else:
            (self.root / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "trace_id": name,
                        "rollout_id": name,
                        "root_thread_id": self.thread,
                        "started_at_unix_ms": self.clock,
                        "raw_event_log": "trace.jsonl",
                        "payloads_dir": "payloads",
                    }
                )
            )
            (self.root / "trace.jsonl").write_text("")
            self.event("rollout_started", trace_id=name, root_thread_id=self.thread)
            self.event(
                "thread_started", thread_id=self.thread, agent_path="/root", metadata_payload=None
            )

    def payload(self, value, kind):
        self.raw += 1
        relative = f"payloads/{self.raw}.json"
        (self.root / relative).write_text(json.dumps(value, ensure_ascii=False))
        return {
            "raw_payload_id": f"raw_payload:{self.raw}",
            "path": relative,
            "kind": {"type": kind},
        }

    def event(self, event_type, **payload):
        self.seq += 1
        self.clock += 100
        value = {
            "schema_version": 1,
            "seq": self.seq,
            "wall_time_unix_ms": self.clock,
            "rollout_id": self.name,
            "thread_id": self.thread,
            "codex_turn_id": self.turn,
            "payload": {"type": event_type, **payload},
        }
        with (self.root / "trace.jsonl").open("a") as stream:
            stream.write(json.dumps(value, ensure_ascii=False) + "\n")

    def start_turn(self, number):
        self.turn = f"turn-{number}"
        self.event("codex_turn_started", thread_id=self.thread, codex_turn_id=self.turn)

    def request(self, number, inputs, previous=None, tools=None):
        raw = {
            "model": "review-model",
            "input": inputs,
            "stream": True,
            "reasoning": {"effort": "medium"},
        }
        if previous:
            raw["previous_response_id"] = previous
        if tools is not None:
            raw["tools"] = tools
        self.event(
            "inference_started",
            inference_call_id=str(number),
            thread_id=self.thread,
            codex_turn_id=self.turn,
            model="review-model",
            provider_name="controlled-review",
            request_payload=self.payload(raw, "inference_request"),
        )

    def response(self, number, items, status="completed"):
        raw = self.payload(
            {
                "output_items": items,
                "token_usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 40,
                    "output_tokens": 20,
                    "reasoning_output_tokens": 5,
                },
            },
            "inference_response",
        )
        if status == "completed":
            self.event(
                "inference_completed",
                inference_call_id=str(number),
                response_id=f"response-{number}",
                upstream_request_id=None,
                response_payload=raw,
            )
        elif status == "cancelled":
            self.event(
                "inference_cancelled",
                inference_call_id=str(number),
                reason="Controlled cancellation",
                upstream_request_id=None,
                partial_response_payload=raw,
            )
        else:
            self.event(
                "inference_failed",
                inference_call_id=str(number),
                error="Controlled provider failure",
                upstream_request_id=None,
                partial_response_payload=raw,
            )

    def tool(self, call, name, args, result=None, failed=False):
        self.event(
            "tool_call_started",
            tool_call_id=call,
            model_visible_call_id=call,
            code_mode_runtime_tool_id=None,
            requester={"type": "model"},
            kind={"type": "other", "name": name},
            summary={
                "type": "generic",
                "label": name,
                "input_preview": json.dumps(args),
                "output_preview": None,
            },
            invocation_payload=self.payload(
                {
                    "tool_name": name,
                    "payload": {
                        "type": "function",
                        "arguments": json.dumps(args, ensure_ascii=False),
                    },
                },
                "tool_invocation",
            ),
        )
        if result is not None:
            self.event(
                "tool_call_ended",
                tool_call_id=call,
                status="failed" if failed else "completed",
                result_payload=self.payload(result, "tool_result"),
            )

    def end(self, status="completed"):
        self.event("codex_turn_ended", codex_turn_id=self.turn, status=status)
        rollout_status = "aborted" if status == "cancelled" else status
        self.event("thread_ended", thread_id=self.thread, status=rollout_status)
        self.event("rollout_ended", status=rollout_status)


def message(role, text):
    return {
        "type": "message",
        "role": role,
        "content": [{"type": "input_text" if role != "assistant" else "output_text", "text": text}],
    }


def call(name, identity, args):
    return {
        "type": "function_call",
        "name": name,
        "call_id": identity,
        "arguments": json.dumps(args),
    }


TOOLS = [
    {
        "type": "function",
        "name": "run_code",
        "description": "Execute a program in `TypeScript`.",
        "parameters": {
            "type": "object",
            "properties": {"code": {"type": "string"}, "description": {"type": "string"}},
        },
    },
    {
        "type": "function",
        "name": "read_file",
        "description": "Read a controlled review fixture. SCHEMA_SEARCH_MARKER",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
    },
]


def build_live():
    live = Capture("review-live")
    live.start_turn(1)
    for number in range(1, 141):
        live.request(
            number,
            [message("user", f"Live history {number}")],
            previous=f"response-{number - 1}" if number > 1 else None,
            tools=TOOLS if number == 1 else None,
        )
        live.response(number, [message("assistant", f"Live history answer {number}.")])
    live.request(
        141, [message("user", "Watch the controlled live append.")], previous="response-140"
    )


def build():
    rich = Capture("review-rich")
    rich.start_turn(1)
    first = [
        message(
            "developer",
            "You are reviewing a synthetic recording.\nKeep all Unicode and whitespace. 🌱",
        ),
        message("user", "# Review fixture\nInspect code, tools and images."),
    ]
    rich.request(1, first, tools=TOOLS)
    program = {
        "code": "const answer: number = 42;\nconsole.log(answer);\n",
        "description": "Calculate the review value",
    }
    rich.response(
        1,
        [
            {
                "type": "reasoning",
                "summary": [
                    {
                        "type": "summary_text",
                        "text": "## Public summary\nCheck the recorded result.",
                    }
                ],
            },
            message("assistant", "I will inspect the fixture."),
            call("run_code", "code-one", program),
        ],
    )
    rich.tool(
        "code-one",
        "run_code",
        program,
        {"output": "42\n", "data": {"answer": 42, "empty": None, "deep": {"values": ["🌱", True]}}},
    )
    rich.request(
        2,
        [{"type": "function_call_output", "call_id": "code-one", "output": "42\n"}],
        previous="response-1",
    )
    rich.response(
        2,
        [
            message(
                "assistant",
                "## Result\n\n**Answer:** 42\n\n| Key | Value |\n| --- | --- |\n| answer | 42 |\n\n```typescript\nconst answer = 42;\n```\n\nFormula: $x^2$.\n",
            )
        ],
    )
    rich.event("codex_turn_ended", codex_turn_id=rich.turn, status="completed")
    rich.start_turn(2)
    image = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI4MCIgaGVpZ2h0PSI0MCI+PHJlY3Qgd2lkdGg9IjgwIiBoZWlnaHQ9IjQwIiBmaWxsPSIjMjg1NGZmIi8+PC9zdmc+"
    attachment = {
        "type": "message",
        "role": "user",
        "content": [
            {"type": "input_text", "text": "Attachment order starts here."},
            {
                "type": "input_image",
                "image_url": image,
                "name": "blue-review.svg",
                "width": 80,
                "height": 40,
            },
            {
                "type": "input_file",
                "filename": "zero-byte-review.txt",
                "size": 0,
                "mime_type": "text/plain",
            },
            {"type": "input_text", "text": "Attachment order ends here."},
        ],
    }
    rich.request(
        3,
        [
            *first,
            message("developer", "New instruction: preserve ordered attachments."),
            attachment,
        ],
        tools=TOOLS[:1],
    )
    rich.response(3, [message("assistant", "The ordered attachments are recorded.")])
    rich.end()

    large = Capture("review-large")
    large.start_turn(1)
    for number in range(420):
        if number and number % 30 == 0:
            large.start_turn(number // 30 + 1)
        large.request(
            number,
            [message("user", f"History record {number:04d} UNIQUE_HISTORY_{number:04d}")],
            previous=f"response-{number - 1}" if number else None,
        )
        large.response(
            number,
            [
                message(
                    "assistant",
                    f"Recorded answer {number:04d}. " + ("Long body for full-content search. " * 8),
                )
            ],
        )
    large.end()

    missing = Capture("review-missing")
    missing.start_turn(1)
    missing.request(
        1,
        [
            message("developer", "Known surviving instruction."),
            message("user", "Known surviving input."),
        ],
        previous="outside-recording",
    )
    missing.response(1, [message("assistant", "Only the known context is available.")])
    missing.end()
    error = Capture("review-error")
    error.start_turn(1)
    error.request(1, [message("user", "Inspect the controlled error.")], tools=TOOLS)
    error.response(1, [call("read_file", "fail-one", {"path": "missing.txt"})])
    error.tool(
        "fail-one",
        "read_file",
        {"path": "missing.txt"},
        {"output": "ENOENT\nControlled failure output.\n", "exit_code": 1},
        True,
    )
    error.request(
        2,
        [{"type": "function_call_output", "call_id": "fail-one", "output": "ENOENT"}],
        previous="response-1",
    )
    error.response(
        2, [message("assistant", "A preserved partial reply before cancellation.")], "cancelled"
    )
    error.end("cancelled")
    build_live()
    unicode = Capture("review-unicode")
    unicode.start_turn(1)
    unicode.request(
        1, [message("developer", "🌱" * 60000), message("user", "Verify lossless Unicode paging.")]
    )
    unicode.response(1, [message("assistant", "Unicode fixture recorded.")])
    unicode.end()
    pictures = Capture("review-tool-images")
    pictures.start_turn(1)
    pictures.request(
        1,
        [message("user", "Inspect tool and code-cell images.")],
        tools=[
            *TOOLS,
            {
                "type": "namespace",
                "name": "functions",
                "tools": [
                    {
                        "type": "custom",
                        "name": "exec",
                        "description": "Execute JavaScript source",
                        "format": {"type": "text"},
                    }
                ],
            },
        ],
    )
    pictures.response(
        1,
        [
            {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "program-image",
                "input": 'image("recorded image");',
            },
            call("read_file", "image-only", {"path": "review.svg"}),
            call("read_file", "broken-image", {"path": "broken.png"}),
        ],
    )
    pictures.event(
        "code_cell_started",
        runtime_cell_id="1",
        model_visible_call_id="program-image",
        source_js='image("recorded image");',
    )
    response = pictures.payload(
        {
            "response": {
                "Result": {
                    "cell_id": "1",
                    "content_items": [
                        {"type": "input_text", "text": "Printed image follows.\n"},
                        {"type": "input_image", "image_url": image},
                    ],
                    "error_text": None,
                }
            }
        },
        "tool_result",
    )
    pictures.event(
        "code_cell_ended", runtime_cell_id="1", status="completed", response_payload=response
    )
    pictures.tool(
        "image-only",
        "read_file",
        {"path": "review.svg"},
        {"content": [{"type": "image", "mimeType": "image/svg+xml", "data": image.split(",")[1]}]},
    )
    pictures.tool(
        "broken-image",
        "read_file",
        {"path": "broken.png"},
        {"content": [{"type": "image", "mimeType": "image/png", "data": "aGVsbG8="}]},
    )
    pictures.request(
        2,
        [
            {
                "type": "custom_tool_call_output",
                "call_id": "program-image",
                "output": "Image printed.",
            },
            {"type": "function_call_output", "call_id": "image-only", "output": "Image returned."},
            {
                "type": "function_call_output",
                "call_id": "broken-image",
                "output": "Invalid image returned.",
            },
        ],
        previous="response-1",
    )
    pictures.response(
        2,
        [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "input_image", "image_url": image}],
            }
        ],
    )
    pictures.end()
    compact = Capture("review-compaction")
    compact.start_turn(1)
    request = compact.payload(
        {"model": "review-model", "input": [message("user", "Compact this controlled history.")]},
        "compaction_request",
    )
    compact.event(
        "compaction_request_started",
        compaction_id="compact-one",
        compaction_request_id="compact-attempt",
        thread_id=compact.thread,
        codex_turn_id=compact.turn,
        model="review-model",
        provider_name="controlled-review",
        request_payload=request,
    )
    response = compact.payload(
        {"output_items": [message("assistant", "Controlled compaction result.")]},
        "compaction_response",
    )
    compact.event(
        "compaction_request_completed",
        compaction_id="compact-one",
        compaction_request_id="compact-attempt",
        response_payload=response,
    )
    compact.event("rollout_ended", status="completed")
    multi = Capture("review-multi")
    multi.start_turn(1)
    multi.request("root", [message("user", "Root thread controlled message.")])
    multi.response("root", [message("assistant", "Root thread answer.")])
    multi.thread = "review-child"
    multi.turn = "child-turn"
    multi.event(
        "thread_started",
        thread_id=multi.thread,
        agent_path="/root/review-worker",
        metadata_payload=None,
    )
    multi.event("codex_turn_started", thread_id=multi.thread, codex_turn_id=multi.turn)
    multi.request("child", [message("user", "Child thread controlled message.")])
    multi.response("child", [message("assistant", "Child thread answer.")])
    multi.event("codex_turn_ended", codex_turn_id=multi.turn, status="completed")
    multi.event("thread_ended", thread_id=multi.thread, status="completed")
    multi.thread = "review-root"
    multi.turn = "turn-1"
    multi.end()
    config = {
        "roots": [str(REVIEW / "recordings"), str(ROOT / "local-context/recordings")],
        "labels": {
            name: f"受控测试：{label}"
            for name, label in [
                ("review-rich", "完整详情与附件"),
                ("review-large", "420 次请求长历史"),
                ("review-missing", "前序缺失"),
                ("review-error", "失败与取消"),
                ("review-live", "实时追加"),
                ("review-compaction", "压缩请求"),
                ("review-multi", "多代理筛选"),
                ("review-unicode", "Unicode 分页"),
                ("review-tool-images", "工具图片与损坏附件"),
            ]
        },
    }
    (REVIEW / "viewer-config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2))
    print(
        json.dumps(
            {"config": str(REVIEW / "viewer-config.json"), "recordings": list(config["labels"])},
            ensure_ascii=False,
        )
    )


def advance():
    live = Capture("review-live", resume=True)
    live.response(141, [call("read_file", "live-tool", {"path": "live.txt"})])
    live.tool(
        "live-tool",
        "read_file",
        {"path": "live.txt"},
        {"output": "LIVE_APPEND_VERIFIED\n", "exit_code": 0},
    )
    live.request(
        142,
        [
            {
                "type": "function_call_output",
                "call_id": "live-tool",
                "output": "LIVE_APPEND_VERIFIED\n",
            }
        ],
        previous="response-141",
    )
    live.response(142, [message("assistant", "Live append completed.")])
    live.end()
    print("Advanced review-live to completion.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--advance-live", action="store_true")
    parser.add_argument("--reset-live", action="store_true")
    args = parser.parse_args()
    advance() if args.advance_live else build_live() if args.reset_live else build()
