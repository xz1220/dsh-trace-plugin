"""One owned synthetic A/B sample shared by reconciliation and browser tests."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from fixtures import Fixture

THREAD = "reconcile-synthetic-thread"
TRACE = "reconcile-synthetic-capture"
ROLLOUT = "reconcile-synthetic-rollout"
MARKERS = {letter: f"RECONCILE_{letter}" for letter in ("A", "B")}
OWNER = ".reconciliation-fixture.json"


class SyntheticFixture(Fixture):
    """Keep header and turn event envelopes within this sample's exact identities."""

    turn = None

    def event(self, record_type, **values):
        event = super().event(record_type, **values)
        event.update(thread_id=THREAD, rollout_id=ROLLOUT)
        if self.turn is None:
            event.pop("codex_turn_id", None)
        else:
            event["codex_turn_id"] = self.turn
        return event


def message(role, text, identity, phase=None):
    item = {
        "type": "message",
        "role": role,
        "id": identity,
        "content": [{"type": "input_text" if role == "user" else "output_text", "text": text}],
    }
    if phase:
        item["phase"] = phase
    return item


def create(directory):
    directory = Path(directory).resolve()
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("Fixture destination must be empty; existing data is preserved.")
    directory.mkdir(parents=True, exist_ok=True)
    fixture = SyntheticFixture(directory / "capture", schema_version=2, started_at=1700000000000)
    manifest_path = fixture.root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest.update(trace_id=TRACE, rollout_id=ROLLOUT, root_thread_id=THREAD)
    manifest_path.write_text(json.dumps(manifest) + "\n")
    chat = {
        "schemaVersion": 1,
        "thread": {"id": THREAD, "title": "Synthetic reconciliation"},
        "turns": [],
    }
    fixture.append("rollout_started", trace_id=TRACE, root_thread_id=THREAD)
    fixture.append("thread_started", thread_id=THREAD, agent_path="/root")
    emit_turn(fixture, chat, "A")
    (directory / "chat.json").write_text(json.dumps(chat, indent=2) + "\n")
    (directory / OWNER).write_text(json.dumps({"owner": "reconciliation-v1", "phase": "A"}) + "\n")
    return directory


def emit_turn(fixture, chat, letter):
    marker, turn = MARKERS[letter], f"turn-{letter}"
    prompt = f"Print '{marker}' using the terminal."
    command = f"printf '%s\\n' '{marker}'"
    input_id, tool_id, final_id = f"input-{letter}", f"tool-{letter}", f"final-{letter}"
    fixture.turn = turn
    fixture.append("codex_turn_started", thread_id=THREAD, codex_turn_id=turn)
    if letter == "A":
        delivered = message("user", prompt, input_id)
        chat_input = {"type": "userMessage", "id": input_id, "text": prompt}
    else:
        delivered = {
            "type": "function_call_output",
            "id": input_id,
            "name": "send_message_to_thread",
            "output": prompt,
        }
        chat_input = {
            "type": "functionCallOutput",
            "id": input_id,
            "name": "send_message_to_thread",
            "output": {"text": prompt, "truncated": False},
        }
    request = {"input": [delivered], "stream": True}
    if letter == "B":
        request["previous_response_id"] = "response-A-final"
    else:
        request["tools"] = [
            {"type": "function", "name": "exec_command", "parameters": {"type": "object"}}
        ]
    fixture.append(
        "inference_started",
        inference_call_id=f"{letter}-call",
        thread_id=THREAD,
        codex_turn_id=turn,
        request_payload=fixture.payload(request, "inference_request"),
    )
    fixture.append(
        "inference_completed",
        inference_call_id=f"{letter}-call",
        response_id=f"response-{letter}-call",
        response_payload=fixture.payload(
            {
                "output_items": [
                    {
                        "type": "function_call",
                        "call_id": tool_id,
                        "name": "exec_command",
                        "arguments": json.dumps({"cmd": command}),
                    }
                ]
            },
            "inference_response",
        ),
    )
    fixture.append(
        "tool_call_started",
        tool_call_id=tool_id,
        model_visible_call_id=tool_id,
        requester={"type": "model"},
        summary={"label": "exec_command"},
        invocation_payload=fixture.payload(
            {"tool_name": "exec_command", "payload": {"arguments": json.dumps({"cmd": command})}},
            "tool_invocation",
        ),
    )
    fixture.append(
        "tool_call_ended",
        tool_call_id=tool_id,
        status="completed",
        result_payload=fixture.payload(
            {"type": "code_mode_response", "value": {"output": marker + "\n", "exit_code": 0}},
            "tool_result",
        ),
    )
    fixture.append(
        "inference_started",
        inference_call_id=f"{letter}-final",
        thread_id=THREAD,
        codex_turn_id=turn,
        request_payload=fixture.payload(
            {
                "stream": True,
                "previous_response_id": f"response-{letter}-call",
                "input": [
                    {"type": "function_call_output", "call_id": tool_id, "output": marker + "\n"}
                ],
            },
            "inference_request",
        ),
    )
    fixture.append(
        "inference_completed",
        inference_call_id=f"{letter}-final",
        response_id=f"response-{letter}-final",
        response_payload=fixture.payload(
            {"output_items": [message("assistant", marker, final_id, "final_answer")]},
            "inference_response",
        ),
    )
    fixture.append("codex_turn_ended", codex_turn_id=turn, status="completed")
    chat["turns"].append(
        {
            "id": turn,
            "status": "completed",
            "items": [
                chat_input,
                {
                    "type": "commandExecution",
                    "id": tool_id,
                    "command": command,
                    "status": "completed",
                    "exitCode": 0,
                    "output": {"text": marker + "\n", "truncated": False},
                },
                {"type": "agentMessage", "id": final_id, "phase": "final_answer", "text": marker},
            ],
        }
    )
    fixture.turn = None


def append_b(directory):
    directory = Path(directory).resolve()
    owner = json.loads((directory / OWNER).read_text())
    if owner != {"owner": "reconciliation-v1", "phase": "A"}:
        raise ValueError("Append requires this tool's phase-A fixture.")
    capture = directory / "capture"
    manifest = json.loads((capture / "manifest.json").read_text())
    if manifest.get("root_thread_id") != THREAD or manifest.get("trace_id") != TRACE:
        raise ValueError("Fixture identity changed; preserving its files.")
    events = [json.loads(line) for line in (capture / "trace.jsonl").read_text().splitlines()]
    chat = json.loads((directory / "chat.json").read_text())
    if (
        chat.get("thread", {}).get("id") != THREAD
        or [turn.get("id") for turn in chat.get("turns", [])] != ["turn-A"]
        or any(event.get("thread_id") != THREAD for event in events)
        or events[-1].get("payload", {}).get("type") != "codex_turn_ended"
    ):
        raise ValueError("Fixture scope changed; preserving its files.")
    fixture = object.__new__(SyntheticFixture)
    fixture.root, fixture.schema_version = capture, 2
    fixture.started_at = manifest["started_at_unix_ms"]
    fixture.seq = events[-1]["seq"]
    fixture.payloads = max(int(path.stem) for path in (capture / "payloads").glob("*.json"))
    emit_turn(fixture, chat, "B")
    (directory / "chat.json").write_text(json.dumps(chat, indent=2) + "\n")
    (directory / OWNER).write_text(json.dumps({"owner": "reconciliation-v1", "phase": "AB"}) + "\n")
