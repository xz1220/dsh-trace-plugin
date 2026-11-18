"""Reconcile an exact, explicitly supplied chat/capture scope without changing recordings."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shlex
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_READER = ROOT / "plugins/codex-dsh-trace/server"
# Reuse path/type/size checks, not the projection's interpretation of recorded facts.
_spec = importlib.util.spec_from_file_location("reconcile_safe_io", DEFAULT_READER / "recording.py")
io = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(io)
STATUSES = (
    "matched",
    "bug",
    "source_missing",
    "source_unreadable",
    "display_difference",
    "undetermined",
)


def digest(value):
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    return {
        "type": type(value).__name__,
        "bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def error_code(error):
    return getattr(error, "code", type(error).__name__)


def read_json(path, limit=io.MAX_PAYLOAD):
    path = Path(path).absolute()
    return io.read_json(io.safe_file(path.parent, path.name), limit)


def text_content(item):
    """Only the official plain-text message/output shapes supported by this check."""
    if isinstance(item, str):
        return item
    if isinstance(item, dict) and isinstance(item.get("text"), str):
        return item["text"]
    if not isinstance(item, dict):
        return None
    content = item.get("content", item.get("output"))
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return text_content(content)
    if isinstance(content, list) and all(
        isinstance(block, dict) and isinstance(block.get("text"), str) for block in content
    ):
        return "\n\n".join(block["text"] for block in content)
    return None


def chat_items(chat, turns):
    items = []
    for turn in chat["turns"]:
        if turn["id"] not in turns:
            continue
        found = set()
        for item in turn.get("items", []):
            kind, value = item.get("type"), None
            if kind == "userMessage":
                kind, value = (
                    "input",
                    {"type": "message", "role": "user", "text": text_content(item)},
                )
            elif kind == "functionCallOutput" and item.get("name") in (
                "create_thread",
                "send_message_to_thread",
            ):
                kind, value = (
                    "input",
                    {
                        "type": "function_call_output",
                        "name": item["name"],
                        "text": text_content(item.get("output")),
                    },
                )
            elif kind == "commandExecution":
                kind, value = (
                    "tool",
                    {
                        "command": item.get("command"),
                        "output": text_content(item.get("output")),
                        "exitCode": item.get("exitCode"),
                    },
                )
            elif kind == "agentMessage" and item.get("phase") == "final_answer":
                kind, value = "final", {"text": text_content(item)}
            if value is not None:
                found.add(kind)
                items.append(
                    {
                        "turnId": turn["id"],
                        "kind": kind,
                        "id": item.get("id"),
                        "value": value,
                        "status": item.get("status"),
                        "truncated": bool(item.get("output", {}).get("truncated"))
                        if isinstance(item.get("output"), dict)
                        else False,
                    }
                )
        for kind in {"input", "tool", "final"} - found:
            items.append({"turnId": turn["id"], "kind": kind, "id": None, "value": {}})
    return items


def issue(status, reason, **values):
    return {"status": status, "reason": reason, **values}


def source_snapshot(paths, thread_id, turn_ids):
    """Manifest gate precedes every event log/body read; no discovery or text guessing."""
    io.identifier(thread_id)
    for turn in turn_ids:
        io.identifier(turn)
    captures, issues, facts, payloads = [], [], [], []
    for supplied in paths:
        path = Path(supplied).absolute()
        try:
            if path.is_symlink():
                raise io.TraceError("", code="recording_symlink")
            manifest = read_json(path / "manifest.json", 1024 * 1024)
            if manifest.get("root_thread_id") != thread_id:
                return [], [issue("undetermined", "wrong_thread_manifest", path=str(path))], [], []
            if (
                type(manifest.get("schema_version")) is not int
                or manifest.get("schema_version") not in (1, 2)
                or manifest.get("raw_event_log") != "trace.jsonl"
            ):
                raise io.TraceError("", code="unsupported_recording_layout")
            io.identifier(manifest.get("trace_id"))
            captures.append({"path": str(path), "manifest": manifest, "events": []})
        except (OSError, ValueError, TypeError, AttributeError) as error:
            status = "source_missing" if not path.exists() else "source_unreadable"
            issues.append(issue(status, error_code(error), path=str(path)))
    # Any invalid/mismatched capture makes the supplied scope incomplete; don't inspect other bodies.
    if issues:
        return [], issues, [], []
    trace_ids = [capture["manifest"]["trace_id"] for capture in captures]
    if len(set(trace_ids)) != len(trace_ids):
        return [], [issue("undetermined", "duplicate_capture_identity")], [], []
    for capture in captures:
        path, manifest = Path(capture["path"]), capture["manifest"]
        trace_id = manifest["trace_id"]
        try:
            log = io.safe_file(path, "trace.jsonl")
            before = log.stat()
            if before.st_size > io.MAX_LOG:
                raise io.TraceError("", code="recording_index_too_large")
            with log.open("rb") as stream:
                raw = stream.read(before.st_size)
            after = log.stat()
            end = raw.rfind(b"\n") + 1
            complete = raw[:end]
            if end != len(raw):
                issues.append(issue("undetermined", "pending_event_tail", traceId=trace_id))
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ino,
            ):
                issues.append(issue("undetermined", "source_changed_during_read", traceId=trace_id))
            records = [json.loads(line) for line in complete.splitlines() if line.strip()]
            for expected, event in enumerate(records, 1):
                if (
                    event.get("seq") != expected
                    or event.get("schema_version") != manifest["schema_version"]
                ):
                    raise io.TraceError("", code="invalid_recording_events")
                body = event["payload"]
                turn = event.get("codex_turn_id") or body.get("codex_turn_id")
                if turn in turn_ids or body.get("type") in ("rollout_started", "thread_started"):
                    if event.get("thread_id") not in (None, thread_id):
                        raise io.TraceError("", code="event_thread_mismatch")
                    capture["events"].append(event)
            capture["evidence"] = {
                "log": {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()},
                "completeEvents": len(records),
                "selectedEvents": len(capture["events"]),
                "pendingBytes": len(raw) - end,
                "manifest": digest(manifest),
            }
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            issues.append(issue("source_unreadable", error_code(error), traceId=trace_id))
            continue
        first_requests = set()
        terminal_tools = set()
        for event in capture["events"]:
            body = event["payload"]
            kind = body["type"]
            turn = event.get("codex_turn_id") or body.get("codex_turn_id")
            if turn not in turn_ids:
                continue
            base = {"turnId": turn, "sourceTraceId": trace_id, "seq": event["seq"]}

            def payload(reference):
                if not isinstance(reference, dict) or not io.PAYLOAD_RE.fullmatch(
                    reference.get("path", "")
                ):
                    raise io.TraceError("", code="unsafe_payload_pointer")
                location = io.safe_file(path, reference["path"])
                before_payload = location.stat()
                result = io.read_json(location)
                after_payload = location.stat()
                if (before_payload.st_size, before_payload.st_mtime_ns, before_payload.st_ino) != (
                    after_payload.st_size,
                    after_payload.st_mtime_ns,
                    after_payload.st_ino,
                ):
                    raise io.TraceError("", code="payload_changed_during_read")
                payloads.append(
                    {"traceId": trace_id, "path": reference["path"], "value": digest(result)}
                )
                return result

            try:
                if kind == "codex_turn_ended":
                    facts.append(
                        {
                            **base,
                            "kind": "turn",
                            "id": turn,
                            "value": {"status": body.get("status", "completed")},
                        }
                    )
                elif kind == "inference_started":
                    request = payload(body.get("request_payload"))
                    inference = body["inference_call_id"]
                    facts.append(
                        {
                            **base,
                            "kind": "request",
                            "id": inference,
                            "inferenceId": inference,
                            "value": {"previousResponseId": request.get("previous_response_id")},
                        }
                    )
                    if turn in first_requests:
                        continue
                    first_requests.add(turn)
                    for item in request["input"]:
                        if not isinstance(item, dict):
                            continue
                        is_input = (
                            item.get("type") in ("message", "input_message")
                            and item.get("role") == "user"
                        )
                        is_delegation = item.get("type") == "function_call_output" and item.get(
                            "name"
                        ) in ("create_thread", "send_message_to_thread")
                        if is_input or is_delegation:
                            value = {
                                key: item[key] for key in ("type", "role", "name") if key in item
                            }
                            if value["type"] == "input_message":
                                value["type"] = "message"
                            value["text"] = text_content(item)
                            facts.append(
                                {
                                    **base,
                                    "kind": "input",
                                    "id": item.get("id"),
                                    "inferenceId": inference,
                                    "value": value,
                                }
                            )
                elif kind == "inference_completed":
                    response = payload(body.get("response_payload"))
                    facts.append(
                        {
                            **base,
                            "kind": "response",
                            "inferenceId": body["inference_call_id"],
                            "id": body.get("response_id"),
                            "responseId": body.get("response_id"),
                            "value": {},
                        }
                    )
                    for item in response["output_items"]:
                        if (
                            item.get("type") == "message"
                            and item.get("role") == "assistant"
                            and item.get("phase") == "final_answer"
                        ):
                            facts.append(
                                {
                                    **base,
                                    "kind": "final",
                                    "id": item.get("id"),
                                    "inferenceId": body["inference_call_id"],
                                    "responseId": body.get("response_id"),
                                    "value": {"text": text_content(item)},
                                }
                            )
                elif kind == "tool_call_started":
                    invocation = payload(body.get("invocation_payload"))
                    if invocation.get("tool_name") != "exec_command":
                        continue
                    arguments = invocation.get("payload", {}).get("arguments")
                    arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
                    tool = body["tool_call_id"]
                    terminal_tools.add(tool)
                    facts.append(
                        {**base, "kind": "tool", "id": tool, "value": {"command": arguments["cmd"]}}
                    )
                elif kind == "tool_call_ended" and body.get("tool_call_id") in terminal_tools:
                    result = payload(body.get("result_payload"))
                    if result.get("type") == "code_mode_response":
                        result = result["value"]
                    facts.append(
                        {
                            **base,
                            "kind": "tool-result",
                            "id": body["tool_call_id"],
                            "value": {
                                "output": result["output"],
                                "exitCode": result["exit_code"],
                                "status": body.get("status"),
                            },
                        }
                    )
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                issues.append(issue("source_unreadable", error_code(error), **base))
    return captures, issues, facts, payloads


def reader_snapshot(captures, thread, turns, directory, reader_dir):
    environment = dict(
        os.environ,
        PYTHONDONTWRITEBYTECODE="1",
        HOME=str(directory / "isolated"),
        CODEX_HOME=str(directory / "isolated/codex"),
        CODEX_ROLLOUT_TRACE_ROOT=str(directory / "isolated/no-discovery"),
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/reconcile_reader.py"),
            "--reader-dir",
            str(reader_dir),
        ],
        input=json.dumps(
            {
                "threadId": thread,
                "turnIds": turns,
                "captures": captures,
                "configDirectory": str(directory / "isolated"),
            }
        ),
        text=True,
        capture_output=True,
        env=environment,
        timeout=60,
        check=False,
    )
    result = json.loads(completed.stdout)
    if completed.returncode and not result.get("errors"):
        result.setdefault("errors", []).append({"code": "reader_process_failed"})
    return result


def shell_display(value):
    if not isinstance(value, str):
        return None
    try:
        parts = shlex.split(value)
        if (
            len(parts) == 3
            and parts[0] in ("/bin/zsh", "/bin/bash", "zsh", "bash", "/bin/sh", "sh")
            and parts[1] in ("-c", "-lc")
        ):
            return parts[2]
    except ValueError:
        pass
    return value


def compare(chat, turns, captures, source_issues, facts, reader):
    results = [dict(item, layer="source", item="scope") for item in source_issues]

    def add(status, reason, entry, field, source=None, actual=None, layer="reader"):
        results.append(
            issue(
                status,
                reason,
                layer=layer,
                item=entry["kind"],
                field=field,
                turnId=entry["turnId"],
                id=entry.get("id"),
                evidence={
                    key: entry[key]
                    for key in ("sourceTraceId", "seq", "inferenceId")
                    if key in entry
                },
                expected=digest(entry.get("value", {}).get(field)),
                source=digest(source),
                reader=digest(actual),
            )
        )

    for turn in chat["turns"]:
        if turn["id"] not in turns:
            continue
        entry = {
            "turnId": turn["id"],
            "kind": "turn",
            "id": turn["id"],
            "value": {"status": "completed"},
        }
        ends = [fact for fact in facts if fact["kind"] == "turn" and fact["turnId"] == turn["id"]]
        completed = (
            turn.get("status") == "completed"
            and not turn.get("error")
            and any(fact["value"]["status"] in ("completed", "complete") for fact in ends)
        )
        add(
            "matched" if completed else "undetermined",
            "completed_turn" if completed else "turn_incomplete_failed_or_absent",
            entry,
            "status",
            "completed" if completed else None,
            layer="chat-source",
        )
    for entry in chat_items(chat, turns):
        fields = {
            "input": ("type", "role", "name", "text"),
            "tool": ("command", "output", "exitCode"),
            "final": ("text",),
        }[entry["kind"]]
        matches = [
            fact
            for fact in facts
            if fact["kind"] == entry["kind"]
            and fact.get("id") == entry.get("id")
            and fact["turnId"] == entry["turnId"]
        ]
        if not entry.get("id") or not entry["value"] or entry["truncated"]:
            add(
                "undetermined",
                "chat_identity_content_absent_or_truncated",
                entry,
                "identity",
                layer="chat-source",
            )
            continue
        if len(matches) != 1:
            relevant_issues = [
                item
                for item in source_issues
                if not item.get("turnId") or item["turnId"] == entry["turnId"]
            ]
            status = relevant_issues[0]["status"] if relevant_issues else "source_missing"
            if len(matches) > 1:
                status = "undetermined"
            add(
                status,
                "source_identity_absent_or_ambiguous",
                entry,
                "identity",
                layer="chat-source",
            )
            continue
        source = matches[0]
        entry.update(
            {key: source[key] for key in ("sourceTraceId", "seq", "inferenceId") if key in source}
        )
        values = dict(source["value"])
        if entry["kind"] == "tool":
            outputs = [
                fact
                for fact in facts
                if fact["kind"] == "tool-result"
                and fact.get("id") == entry["id"]
                and fact["turnId"] == entry["turnId"]
                and fact["sourceTraceId"] == source["sourceTraceId"]
            ]
            if len(outputs) == 1:
                values.update(outputs[0]["value"])
        reader_matches = [
            item
            for item in reader.get("items", [])
            if item["kind"] == entry["kind"]
            and item["turnId"] == entry["turnId"]
            and item.get("sourceTraceId") == source["sourceTraceId"]
            and (
                item.get("inferenceId") == source.get("inferenceId")
                if entry["kind"] == "final"
                else item.get("id") == entry["id"]
            )
        ]
        read = reader_matches[0].get("value", {}) if len(reader_matches) == 1 else {}
        if entry["kind"] == "tool" and (
            entry.get("status") not in ("completed", "complete")
            or values.get("status") not in ("completed", "complete")
            or values.get("exitCode") not in (None, 0)
        ):
            add(
                "undetermined",
                "terminal_not_successfully_completed",
                entry,
                "exitCode",
                values.get("exitCode"),
                read.get("exitCode"),
                layer="chat-source",
            )
        for field in fields:
            expected = entry["value"].get(field)
            if field not in entry["value"] and field not in values:
                continue
            raw = values.get(field)
            actual = read.get(field)
            if raw is None or expected is None:
                status = (
                    "source_unreadable"
                    if any(
                        item["status"] == "source_unreadable"
                        and item.get("turnId") in (None, entry["turnId"])
                        for item in source_issues
                    )
                    else "undetermined"
                )
                add(
                    status,
                    "required_field_absent_or_unsupported",
                    entry,
                    field,
                    raw,
                    actual,
                    layer="chat-source",
                )
                continue
            if expected != raw:
                display = field == "command" and shell_display(expected) == shell_display(raw)
                # Only an explicit shell wrapper is normalized; stdout and exit remain exact.
                add(
                    "display_difference" if display else "bug",
                    "shell_wrapper" if display else "chat_raw_mismatch",
                    entry,
                    field,
                    raw,
                    actual,
                    layer="chat-source",
                )
            else:
                add("matched", "chat_raw_exact", entry, field, raw, raw, layer="chat-source")
            add(
                "matched" if actual == raw else "bug",
                "reader_exact" if actual == raw else "reader_missing_or_mismatch",
                entry,
                field,
                raw,
                actual,
            )
        if entry["kind"] == "input" and values.get("type") == "function_call_output":
            add(
                "display_difference",
                "delegation_is_context_not_user_message",
                entry,
                "type",
                values["type"],
                read.get("type"),
                layer="presentation",
            )
    # Explicit response links are the only continuation oracle; array order/text are irrelevant.
    finals = {
        fact.get("responseId"): fact
        for fact in facts
        if fact["kind"] == "final" and fact.get("responseId")
    }
    linked_turns = set()
    for request in [fact for fact in facts if fact["kind"] == "request"]:
        previous = request["value"].get("previousResponseId")
        predecessor = finals.get(previous)
        if not predecessor or predecessor["turnId"] == request["turnId"]:
            continue
        linked_turns.update((predecessor["turnId"], request["turnId"]))
        candidates = [
            item
            for item in reader.get("continuation", [])
            if item.get("sourceTraceId") == request["sourceTraceId"]
            and item.get("inferenceId") == request["inferenceId"]
            and item.get("turnId") == request["turnId"]
        ]
        good = (
            len(candidates) == 1
            and candidates[0].get("previousResponseId") == previous
            and candidates[0].get("contextComplete") is True
        )
        results.append(
            issue(
                "matched" if good else "bug",
                "explicit_turn_continuation" if good else "reader_continuation_mismatch",
                layer="reader",
                item="continuation",
                turnId=request["turnId"],
                predecessorTurnId=predecessor["turnId"],
            )
        )
    if len(turns) > 1 and set(turns) != linked_turns:
        results.append(
            issue(
                "undetermined",
                "selected_turns_not_connected_by_final_response_ids",
                layer="source",
                item="continuation",
            )
        )

    def identity(item):
        return (
            item.get("sourceTraceId"),
            item.get("turnId"),
            item.get("kind"),
            item.get("inferenceId") if item.get("kind") == "final" else item.get("id"),
        )

    source_keys = {identity(item) for item in facts if item["kind"] in ("input", "tool", "final")}
    seen_reader = set()
    for item in reader.get("items", []):
        key = identity(item)
        if key not in source_keys or key in seen_reader:
            results.append(
                issue(
                    "bug",
                    "reader_extra_duplicate_or_wrong_turn",
                    layer="reader",
                    item=item.get("kind"),
                    turnId=item.get("turnId"),
                    id=item.get("id"),
                )
            )
        seen_reader.add(key)
    requests = {
        (fact["sourceTraceId"], fact["inferenceId"]): fact
        for fact in facts
        if fact["kind"] == "request"
    }
    responses = [fact for fact in facts if fact["kind"] == "response"]

    def source_chain_complete(request):
        visited = set()
        while previous := request["value"].get("previousResponseId"):
            key = (request["sourceTraceId"], request["inferenceId"])
            if key in visited:
                return False
            visited.add(key)
            candidates = [
                response for response in responses if response.get("responseId") == previous
            ]
            local = [
                response
                for response in candidates
                if response["sourceTraceId"] == request["sourceTraceId"]
            ]
            candidates = local or candidates
            if len(candidates) != 1:
                return False
            response = candidates[0]
            request = requests.get((response["sourceTraceId"], response["inferenceId"]))
            if request is None:
                return False
        return True

    for request in requests.values():
        contexts = [
            context
            for context in reader.get("continuation", [])
            if context.get("sourceTraceId") == request["sourceTraceId"]
            and context.get("inferenceId") == request["inferenceId"]
            and context.get("turnId") == request["turnId"]
        ]
        if not source_chain_complete(request):
            results.append(
                issue(
                    "undetermined",
                    "predecessor_outside_supplied_evidence",
                    layer="source",
                    item="context",
                    turnId=request["turnId"],
                )
            )
        elif (
            len(contexts) != 1
            or contexts[0].get("contextComplete") is not True
            or contexts[0].get("previousResponseId") != request["value"].get("previousResponseId")
        ):
            results.append(
                issue(
                    "bug",
                    "reader_context_missing_or_incomplete",
                    layer="reader",
                    item="context",
                    turnId=request["turnId"],
                )
            )
    for error in reader.get("errors", []):
        results.append(
            issue(
                "bug" if facts and not source_issues else "undetermined",
                "reader_error",
                layer="reader",
                item="reader",
                code=error.get("code", "unknown"),
            )
        )
    return results


def report_directory(path, inputs):
    if Path(path).is_symlink():
        raise ValueError("Report destination must not be a symlink.")
    path = Path(path).resolve()
    for supplied in inputs:
        supplied = Path(supplied).resolve()
        if supplied == path or supplied in path.parents:
            raise ValueError("Output must be separate from all read-only inputs.")
    marker = path / ".reconciliation-report.json"
    if (
        path.exists()
        and any(path.iterdir())
        and (not marker.is_file() or read_json(marker) != {"owner": "reconciliation-report-v1"})
    ):
        raise ValueError("Report directory must be empty or owned by this tool.")
    for name in ("report.json", "report.md"):
        candidate = path / name
        if candidate.is_symlink() or (
            candidate.exists() and (not candidate.is_file() or candidate.stat().st_nlink != 1)
        ):
            raise ValueError("Report files must be independent ordinary files.")
    path.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"owner": "reconciliation-report-v1"}) + "\n")
    return path


def check(args):
    output = report_directory(args.output, [args.chat, *args.capture])
    chat_error = None
    try:
        chat = read_json(args.chat)
    except (OSError, ValueError) as error:
        chat, chat_error = {}, error_code(error)
    valid_chat = (
        isinstance(chat, dict)
        and isinstance(chat.get("thread"), dict)
        and isinstance(chat.get("turns"), list)
        and all(
            isinstance(turn, dict)
            and isinstance(turn.get("id"), str)
            and isinstance(turn.get("items"), list)
            and all(isinstance(item, dict) for item in turn["items"])
            for turn in chat["turns"]
        )
    )
    if not valid_chat or chat["thread"].get("id") != args.thread_id:
        results = [
            issue(
                "source_unreadable" if chat_error or not valid_chat else "undetermined",
                chat_error or ("invalid_chat_shape" if not valid_chat else "wrong_thread_chat"),
                layer="chat-source",
                item="scope",
            )
        ]
        captures, facts, payloads, reader = [], [], [], {}
        turns = args.turn_id or []
    else:
        turns = args.turn_id or [turn["id"] for turn in chat["turns"]]
        if (
            not turns
            or not io.ID_RE.fullmatch(args.thread_id)
            or any(not isinstance(turn, str) or not io.ID_RE.fullmatch(turn) for turn in turns)
            or len(set(turns)) != len(turns)
            or any(sum(item.get("id") == turn for item in chat["turns"]) != 1 for turn in turns)
            or any(turn not in {item["id"] for item in chat["turns"]} for turn in turns)
        ):
            results = [
                issue(
                    "undetermined",
                    "requested_turn_absent_or_ambiguous",
                    layer="scope",
                    item="scope",
                )
            ]
            captures, facts, payloads, reader = [], [], [], {}
        else:
            captures, errors, facts, payloads = source_snapshot(args.capture, args.thread_id, turns)
            if errors:
                # Do not run projection against incomplete/unreadable scope or payloads.
                reader = {
                    "items": [],
                    "continuation": [],
                    "errors": [],
                    "provenance": {"kind": "not_run_incomplete_source"},
                }
                results = [dict(item, layer="source", item="scope") for item in errors]
                results.extend(
                    issue(
                        "undetermined",
                        "reader_not_run_incomplete_source",
                        layer="reader",
                        item="scope",
                        turnId=turn,
                    )
                    for turn in turns
                )
            elif not all(
                (args.reader_dir / filename).is_file()
                for filename in ("store.py", "bundle_index.py", "recording.py", "projection.py")
            ):
                reader = {
                    "provenance": {
                        "kind": "not_run_invalid_reader",
                        "readerDir": str(args.reader_dir),
                    }
                }
                results = [
                    issue(
                        "source_unreadable",
                        "reader_directory_unavailable",
                        layer="reader-configuration",
                        item="scope",
                    )
                ]
            else:
                try:
                    reader = reader_snapshot(
                        captures, args.thread_id, turns, output, args.reader_dir
                    )
                except (OSError, ValueError, subprocess.TimeoutExpired) as error:
                    reader = {
                        "items": [],
                        "continuation": [],
                        "errors": [{"code": error_code(error)}],
                    }
                results = compare(chat, turns, captures, errors, facts, reader)
    counts = Counter(item["status"] for item in results)
    code = (
        1
        if counts["bug"]
        else (
            2
            if not results
            or any(
                counts[state] for state in ("source_missing", "source_unreadable", "undetermined")
            )
            else 0
        )
    )
    report = {
        "schemaVersion": 1,
        "timeUtc": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "threadId": args.thread_id,
            "turnIds": turns,
            "chat": str(Path(args.chat).absolute()),
            "chatHash": digest(chat),
            "capturePaths": [str(Path(value).absolute()) for value in args.capture],
        },
        "provenance": {
            "oracle": "official raw fields; projection is a separate subject",
            "toolHash": digest(Path(__file__).read_text()),
            "reader": reader.get("provenance", {}),
            "nativeDesktopAcceptance": False,
        },
        "captures": [
            {
                "path": item["path"],
                "traceId": item["manifest"]["trace_id"],
                **item.get("evidence", {}),
            }
            for item in captures
        ],
        "payloadEvidence": payloads,
        "counts": {state: counts[state] for state in STATUSES},
        "exitCode": code,
        "result": "passed" if code == 0 else "bug" if code == 1 else "insufficient_evidence",
        "items": results,
    }
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    lines = [
        "# Reconciliation",
        "",
        f"Result: **{report['result']}** (exit {code})",
        "",
        f"Thread: `{args.thread_id}`; selected turns: " + ", ".join(f"`{turn}`" for turn in turns),
        f"Chat export: `{report['scope']['chat']}`",
        "Capture paths: " + ", ".join(f"`{path}`" for path in report["scope"]["capturePaths"]),
        f"Reader: `{reader.get('provenance', {}).get('readerDir', args.reader_dir)}` (offline; hashes in report.json)",
        "",
        "Counts: " + ", ".join(f"{key}={value}" for key, value in report["counts"].items()),
        "",
        "| Status | Layer | Turn | Item/field | Reason |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| {item['status']} | {item.get('layer', '')} | {item.get('turnId', '')} | {item.get('item', '')}/{item.get('field', '')} | {item['reason']} |"
        for item in results
    )
    lines.extend(
        [
            "",
            "Values are represented by type, length and SHA-256. This is an offline reader check; it does not establish native desktop binding, rendering or reload.",
            "",
        ]
    )
    (output / "report.md").write_text("\n".join(lines))
    print(
        json.dumps(
            {
                "result": report["result"],
                "counts": report["counts"],
                "report": str(output / "report.json"),
            }
        )
    )
    return code


def serve(args):
    from reconcile_fixture import OWNER, THREAD, TRACE

    directory = args.fixture.absolute()
    if read_json(directory / OWNER).get("owner") != "reconciliation-v1":
        raise ValueError("Only this tool's synthetic fixture may be served.")
    manifest = read_json(directory / "capture/manifest.json")
    if (
        (directory / "capture").is_symlink()
        or manifest.get("root_thread_id") != THREAD
        or manifest.get("trace_id") != TRACE
    ):
        raise ValueError("Synthetic fixture scope changed; refusing to serve.")
    os.environ["CODEX_HOME"] = str(directory / "isolated/codex")
    os.environ["CODEX_ROLLOUT_TRACE_ROOT"] = str(directory / "capture")
    sys.path.insert(0, str(DEFAULT_READER))
    import main
    from store import Store

    store = Store(directory / "isolated/viewer-config.json")
    store.catalog.roots = lambda: [directory / "capture"]
    with main.create_preview_server(args.port, TRACE, store=store) as server:
        print(json.dumps({"url": server.open_url, "port": server.server_port}), flush=True)
        server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fixture = commands.add_parser("fixture", help="Create the shared synthetic phase-A sample.")
    fixture.add_argument("--output", required=True, type=Path)
    fixture.add_argument("--append-b", action="store_true")
    verify = commands.add_parser(
        "check", help="Read only an explicitly scoped export and capture(s)."
    )
    verify.add_argument("--chat", required=True, type=Path)
    verify.add_argument("--capture", action="append", required=True, type=Path)
    verify.add_argument("--thread-id", required=True)
    verify.add_argument("--turn-id", action="append")
    verify.add_argument("--reader-dir", type=Path, default=DEFAULT_READER)
    verify.add_argument("--output", required=True, type=Path)
    preview = commands.add_parser(
        "serve", help="Serve this tool's synthetic fixture through the real bridge harness."
    )
    preview.add_argument("--fixture", required=True, type=Path)
    preview.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    try:
        if args.command == "fixture":
            from reconcile_fixture import append_b, create

            append_b(args.output) if args.append_b else create(args.output)
            print(
                json.dumps(
                    {
                        "fixture": str(args.output.absolute()),
                        "phase": "AB" if args.append_b else "A",
                    }
                )
            )
            return 0
        if args.command == "serve":
            serve(args)
            return 0
        return check(args)
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({"result": "insufficient_evidence", "code": error_code(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
