"""Codex recording → DSH trajectory records. Bodies remain app-only and lazy."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections import OrderedDict
from itertools import islice
from pathlib import Path
from typing import Any, Optional

from store import TraceError, compaction_info, item_text, preview, unpack

GROUP_LABELS = json.loads(
    Path(__file__).with_name("trajectory-locales.json").read_text(encoding="utf-8")
)


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2)


def public_reasoning(item):
    parts = item.get("summary")
    return (
        "\n\n".join(
            part["text"]
            for part in parts
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
        if isinstance(parts, list)
        else ""
    )


def message_text(item):
    content = item.get("content", [])
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return item.get("text", "") if isinstance(item.get("text"), str) else ""
    text_parts = [
        block.get("text", block.get("refusal")) for block in content if isinstance(block, dict)
    ]
    return "\n\n".join(part for part in text_parts if isinstance(part, str))


def message_identity(item):
    if not isinstance(item, dict) or item.get("type") not in ("message", "input_message"):
        return None
    metadata = item.get("internal_chat_message_metadata_passthrough")
    if not isinstance(metadata, dict):
        metadata = {}
    identity = item.get("id") or metadata.get("turn_id")
    if not identity:
        return None
    # Keep genuinely repeated messages and changed content; ignore transport metadata.
    content = json.dumps(item.get("content", []), ensure_ascii=False, sort_keys=True)
    return (str(identity), item.get("role"), hashlib.sha256(content.encode()).hexdigest())


def usage(value):
    if not isinstance(value, dict):
        return None
    keys = {
        "cacheRead": "cached_input_tokens",
        "cacheWrite": "cache_write_input_tokens",
        "output": "output_tokens",
        "reasoning": "reasoning_output_tokens",
    }
    result = {
        key: value[source]
        for key, source in keys.items()
        if isinstance(value.get(source), (int, float))
    }
    if isinstance(value.get("input_tokens"), (int, float)):
        # DSH's input/cache buckets are disjoint. Codex's input_tokens includes cache.
        result["input"] = max(
            0, value["input_tokens"] - result.get("cacheRead", 0) - result.get("cacheWrite", 0)
        )
    return result or None


def catalog_tools(value):
    """Keep complete recorded declarations, normalizing only DSH's display shape."""
    tools: list[dict[str, Any]] = []
    for entry in value or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") == "namespace":
            children = catalog_tools(entry.get("tools"))
            tools.extend(
                {
                    **tool,
                    "sourceName": tool.get("sourceName", tool["name"]),
                    "name": f"{entry.get('name', '')}.{tool['name']}",
                }
                for tool in children
            )
            continue
        tool = entry.get("function", entry)
        if isinstance(tool, dict):
            tools.append(
                {
                    **tool,
                    "name": tool.get("name", entry.get("type", "unknown")),
                    "parameters": tool.get(
                        "parameters", tool.get("input_schema", tool.get("format", {}))
                    ),
                }
            )
    return tools


def recorded_tool_declaration(tools, name):
    """Read one complete runtime declaration from this request's recorded docs."""
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_$][\w$]*", name):
        return ""
    matches = set()
    signature = re.compile(r"\A\s*declare\s+const\s+tools\s*:\s*\{\s*" + re.escape(name) + r"\s*\(")
    for tool in tools:
        if tool.get("name") != "functions.exec" or not isinstance(tool.get("description"), str):
            continue
        for section in re.finditer(
            r"^### `([^`\r\n]+)`[^\S\r\n]*\r?\n(.*?)(?=^### |\Z)", tool["description"], re.M | re.S
        ):
            if section[1] != name:
                continue
            blocks = list(
                re.finditer(
                    r"^```(?:ts|typescript)[^\S\r\n]*\r?\n(.*?)^```[^\S\r\n]*\r?$",
                    section[2],
                    re.M | re.S,
                )
            )
            if (
                len(blocks) == 1
                and signature.match(blocks[0][1])
                and blocks[0][1].rstrip().endswith("};")
            ):
                matches.add(section[0].strip())
    return next(iter(matches)) if len(matches) == 1 else ""


def source_blocks(item, owner, label, metadata_only=False):
    """Preserve block order, original roles, attachments, and publicly returned text."""
    blocks = []
    contents = item.get("content", []) if isinstance(item, dict) else []
    if isinstance(contents, str):
        contents = [{"type": "text", "text": contents}]
    for position, block in enumerate(contents):
        if not isinstance(block, dict):
            blocks.append({"type": "unknown", "content": "" if metadata_only else json_text(block)})
            continue
        kind = block.get("type", "unknown")
        if isinstance(block.get("text", block.get("refusal")), str):
            blocks.append({"type": "text", "content": block.get("text", block.get("refusal"))})
        elif kind in ("input_image", "output_image", "image"):
            url = block.get("image_url", block.get("url"))
            if isinstance(url, dict):
                url = url.get("url")
            if (
                url is None
                and isinstance(block.get("data"), str)
                and str(block.get("mimeType", "")).startswith("image/")
            ):
                url = f"data:{block['mimeType']};base64,{block['data']}"
            asset_id = f"{owner}:{label}:{position}"
            attachment: dict[str, Any] = {"attachmentId": asset_id}
            name = block.get("filename", block.get("name"))
            if isinstance(name, str):
                attachment["name"] = name
            for key in ("width", "height"):
                if isinstance(block.get(key), (int, float)) and block[key] > 0:
                    attachment[key] = block[key]
            if not metadata_only and isinstance(url, str) and url.startswith("data:image/"):
                attachment["recordedUrl"] = url
                header, _, encoded = url.partition(",")
                attachment["mediaType"] = header[5:].split(";")[0]
                if ";base64" in header:
                    try:
                        data = base64.b64decode(encoded, validate=True)
                        attachment["bytes"] = len(data)
                        attachment["attachmentId"] = hashlib.sha256(data).hexdigest()
                        if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
                            attachment.setdefault("width", int.from_bytes(data[16:20], "big"))
                            attachment.setdefault("height", int.from_bytes(data[20:24], "big"))
                    except ValueError:
                        pass
            # Never make a network request or read an arbitrary local path from a trace.
            blocks.append(
                {
                    "type": "image",
                    "content": "" if metadata_only else json_text(block),
                    "attachment": attachment,
                }
            )
        elif kind in ("input_file", "output_file", "file"):
            ref = {
                "attachmentId": f"{owner}:{label}:{position}",
                "name": block.get("filename", block.get("name", "未命名文件")),
            }
            for source, target in [
                ("mime_type", "mediaType"),
                ("mimeType", "mediaType"),
                ("size", "bytes"),
                ("bytes", "bytes"),
            ]:
                if source in block:
                    ref[target] = block[source]
            blocks.append(
                {"type": "file", "content": "" if metadata_only else json_text(block), "file": ref}
            )
        else:
            blocks.append({"type": kind, "content": "" if metadata_only else json_text(block)})
    return blocks


def result_view(raw, code=False):
    """Read recorded content blocks without mistaking business JSON for an envelope."""
    value = unpack(raw, code=code)
    rendered = value
    if code and isinstance(value, dict) and isinstance(value.get("Result"), dict):
        rendered = value["Result"]
    contents = None
    if isinstance(rendered, dict):
        for key in ("content_items", "content"):
            if isinstance(rendered.get(key), list):
                contents = list(rendered[key])
                break
    if contents is not None:
        text = "\n\n".join(
            block["text"]
            for block in contents
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        )
        fallback = rendered.get("error_text")
        if (
            not any(
                isinstance(block, dict)
                and isinstance(block.get("text"), str)
                and len(block["text"]) > 0
                for block in contents
            )
            and isinstance(fallback, str)
            and fallback
        ):
            contents.append({"type": "text", "text": fallback})
            text = fallback
        images = sum(
            isinstance(block, dict)
            and block.get("type") in ("image", "input_image", "output_image")
            for block in contents
        )
        if not text and images:
            text = f"图片 ×{images}"
        return text, contents, isinstance(rendered, dict) and rendered.get("isError") is True
    output = rendered.get("output", rendered) if isinstance(rendered, dict) else rendered
    return output, None, isinstance(rendered, dict) and rendered.get("isError") is True


def bounded_json_preview(value, depth=0):
    if isinstance(value, str):
        return value[:256] + ("…" if len(value) > 256 else "")
    if isinstance(value, dict):
        if depth >= 2:
            return f"{{{len(value)} 个字段}}"
        return {
            key: bounded_json_preview(item, depth + 1) for key, item in islice(value.items(), 4)
        }
    if isinstance(value, list):
        if depth >= 2:
            return f"[{len(value)} 项]"
        return [bounded_json_preview(item, depth + 1) for item in value[:4]]
    return value


class Projection:
    def __init__(self, index):
        self.index = index
        self.cache = OrderedDict()
        self.detail_cache = OrderedDict()
        self.detail_bytes = 0
        self.structure_stamp = None
        self.request_rows = []
        self.request_numbers = {}
        self.request_steps = {}
        self.previous_requests = {}
        self.inherited_requests = {}
        self.turn_numbers = {}
        self.locations = {}
        self.history_turn_key = None
        self.history_turn_ids = []

    def requests(self):
        stamp = (self.index.epoch, self.index.last_seq)
        if stamp != self.structure_stamp:
            if self.structure_stamp is not None and self.structure_stamp[0] != self.index.epoch:
                self.cache.clear()
                self.detail_cache.clear()
                self.detail_bytes = 0
                self.history_turn_key = None
                self.history_turn_ids = []
            self.request_rows = [
                row
                for row in self.index.rows.values()
                if row.get("type") in ("request", "compaction")
            ]
            self.request_numbers = {
                row["id"]: number + 1 for number, row in enumerate(self.request_rows)
            }
            first = next((row for row in self.request_rows if row.get("type") == "request"), None)
            first_ref = first.get("_request") if first else None
            history_key = (first["id"], first_ref.get("path")) if first and first_ref else None
            if history_key != self.history_turn_key:
                raw = self.index.payload(first_ref) or {}
                history_turns: dict[str, None] = {}
                for item in raw.get("input", []):
                    if (
                        not isinstance(item, dict)
                        or item.get("type") not in ("message", "input_message")
                        or item.get("role") not in ("user", "assistant")
                    ):
                        continue
                    metadata = item.get("internal_chat_message_metadata_passthrough")
                    turn_id = metadata.get("turn_id") if isinstance(metadata, dict) else None
                    if isinstance(turn_id, str) and turn_id:
                        history_turns.setdefault(turn_id, None)
                self.history_turn_ids = list(history_turns)
                self.history_turn_key = history_key
            # A resumed bundle carries earlier conversation turns in its first full input.
            turn_ids = dict.fromkeys([*self.history_turn_ids, *self.index.turns])
            self.turn_numbers = {key: number + 1 for number, key in enumerate(turn_ids)}
            self.request_steps = {}
            self.previous_requests = {}
            self.inherited_requests = {}
            self.locations = {}
            counters: dict[tuple[str, Optional[str]], int] = {}
            previous: dict[str, dict[str, Any]] = {}
            root_path = self.index.threads.get(self.index.meta.get("threadId"))
            for row in self.request_rows:
                if row.get("type") != "request":
                    continue
                key = (row["threadId"], row.get("turnId"))
                counters[key] = counters.get(key, 0) + 1
                self.request_steps[row["id"]] = counters[key]
                self.previous_requests[row["id"]] = previous.get(row["threadId"])
                if (
                    row["threadId"] not in previous
                    and isinstance(root_path, str)
                    and root_path.startswith("/")
                ):
                    path = self.index.threads.get(row["threadId"])
                    if isinstance(path, str) and path.startswith(root_path.rstrip("/") + "/"):
                        ancestors = []
                        for thread, candidate in previous.items():
                            ancestor_path = self.index.threads.get(thread)
                            if (
                                isinstance(ancestor_path, str)
                                and ancestor_path.startswith("/")
                                and path.startswith(ancestor_path.rstrip("/") + "/")
                                and candidate["start"] <= row["start"]
                            ):
                                ancestors.append((len(ancestor_path), candidate["seq"], candidate))
                        if ancestors:
                            self.inherited_requests[row["id"]] = max(
                                ancestors, key=lambda item: item[:2]
                            )[2]
                previous[row["threadId"]] = row
            self.structure_stamp = stamp
        return self.request_rows

    def location(self, row):
        requests = self.requests()
        if row["id"] in self.locations:
            return self.locations[row["id"]]
        key = row.get("turnId")
        turn = self.turn_numbers.get(key, 1 if key and row.get("type") != "compaction" else None)
        parent = row
        visited = set()
        while parent and parent.get("type") not in ("request", "compaction"):
            if parent["id"] in visited:
                break
            visited.add(parent["id"])
            parent = self.index.rows.get(parent.get("parentId"))
        if not parent or parent.get("type") not in ("request", "compaction"):
            parent = next(
                (
                    candidate
                    for candidate in reversed(requests)
                    if candidate["seq"] < row["seq"] and candidate["threadId"] == row["threadId"]
                ),
                row,
            )
        if parent.get("type") == "compaction":
            result = (turn, 0, f"压缩 {parent['seq']}", parent)
        else:
            step = self.request_steps.get(parent["id"], 1)
            result = (turn, step, f"第 {step} 步", parent)
        self.locations[row["id"]] = result
        return result

    def request_info(self, row, cumulative=False):
        turn, step, group, _ = self.location(row)
        request = self.index.payload(row.get("_request")) or {}
        response = self.index.payload(row.get("_response")) or {}
        options = {key: value for key, value in request.items() if key not in ("input", "tools")}
        data = {
            "rowId": row["id"],
            "version": row.get("_updated"),
            "seq": row["seq"],
            "turn": turn,
            "step": step,
            "group": group,
            "number": self.request_numbers[row["id"]],
            "status": "error" if row["status"] in ("error", "cancelled") else row["status"],
            "startedAt": row["start"],
            "completedAt": row.get("end"),
            "model": row.get("model", request.get("model")),
            "requestConfig": options,
        }
        if row.get("provider"):
            data["provider"] = row["provider"]
        inspectable = any(
            isinstance(item, dict)
            and (
                item.get("type") in ("message", "function_call", "custom_tool_call")
                or public_reasoning(item)
            )
            for item in response.get("output_items", [])
        )
        if row.get("end") is not None and (
            inspectable or row.get("type") == "compaction" and row.get("_response")
        ):
            data["resultSeq"] = row["seq"]
        if row.get("_error"):
            data["error"] = (
                row["_error"] if isinstance(row["_error"], str) else json_text(row["_error"])
            )
        if row.get("type") == "compaction":
            data.update(purpose="compaction", step=0)
        reported = usage(response.get("token_usage"))
        if reported:
            data["usage"] = reported
        if cumulative:
            total: dict[str, float] = {}
            for candidate in self.requests():
                if candidate["seq"] > row["seq"]:
                    break
                if candidate["threadId"] != row["threadId"]:
                    continue
                value = self.index.payload(candidate.get("_response")) or {}
                for key, amount in (usage(value.get("token_usage")) or {}).items():
                    total[key] = total.get(key, 0) + amount
            if total:
                data["cumulativeUsage"] = total
        return data

    def prompt(self, row):
        context = self.index.context(row["id"])
        entries = [entry["value"] for entry in context["items"] if isinstance(entry["value"], dict)]
        system = "\n\n".join(
            f"[{item.get('role', 'developer')}]\n{item_text(item)}"
            for item in entries
            if item.get("role") in ("system", "developer")
            and item.get("type") != "additional_tools"
        )
        tools = catalog_tools(context.get("tools"))
        for item in entries:
            if item.get("type") == "additional_tools":
                tools.extend(catalog_tools(item.get("tools")))
        effective = OrderedDict()
        for tool in tools:
            effective[tool["name"]] = tool
        return {
            "system": system,
            "tools": list(effective.values()),
            "config": self.request_info(row)["requestConfig"],
        }

    def cells(self, row):
        self.requests()
        ancestor = self.inherited_requests.get(row["id"])
        dependency = (ancestor["id"], ancestor.get("_updated")) if ancestor else None
        key = (row["id"], row.get("_updated"), dependency)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        turn, step, group, parent = self.location(row)
        duration = max(0, row["end"] - row["start"]) / 1000 if row.get("end") is not None else None
        base = {
            "rowId": row["id"],
            "seq": row["seq"],
            "turn": turn,
            "step": step,
            "group": group,
            "threadId": row["threadId"],
            "version": row.get("_updated"),
            "sourceSeq": row["seq"],
            "startedAt": row["start"],
            "timeSeconds": duration,
            "isError": row["status"] in ("error", "cancelled"),
            "detailsPending": True,
        }
        cells = []
        if row.get("type") == "request":
            raw = self.index.payload(row.get("_request")) or {}
            inputs = raw.get("input", [])
            response = self.index.payload(row.get("_response")) or {}
            previous = self.previous_requests.get(row["id"])
            replay_previous = previous or self.inherited_requests.get(row["id"])
            # A full request can replay an earlier prefix. Retain only newly introduced items.
            skip = 0
            known = []
            if not raw.get("previous_response_id") and replay_previous:
                before = self.index.context(replay_previous["id"])
                # A fork may start while an ancestor is still producing its response.
                completed = replay_previous.get("end")
                if replay_previous.get("sourceTraceId") == row.get("sourceTraceId"):
                    completed_before = (
                        completed is not None
                        and completed <= row["start"]
                        and replay_previous.get("_sourceVersion", replay_previous["_updated"])
                        < row.get("sourceEventSeq", row["seq"])
                    )
                else:
                    completed_before = completed is not None and completed < row["start"]
                output = (
                    (self.index.payload(replay_previous.get("_response")) or {})
                    if completed_before
                    else {}
                )
                known = [entry["value"] for entry in before["items"]] + output.get(
                    "output_items", []
                )
                while skip < min(len(inputs), len(known)) and inputs[skip] == known[skip]:
                    skip += 1
            introduced = list(enumerate(inputs))[skip:]
            known_messages = {
                identity for item in known if (identity := message_identity(item)) is not None
            }
            introduced = [
                (position, item)
                for position, item in introduced
                if (identity := message_identity(item)) is None or identity not in known_messages
            ]
            user_positions = [
                position
                for position, item in introduced
                if isinstance(item, dict)
                and item.get("role") == "user"
                and item.get("type") in ("message", "input_message")
                and not message_text(item)
                .lstrip()
                .startswith(("<environment_context>", "<turn_aborted>", "<codex_internal_context"))
            ]
            last_user = user_positions[-1] if user_positions else None
            has_prompt = (
                any(
                    isinstance(item, dict) and item.get("role") in ("developer", "system")
                    for _, item in introduced
                )
                or raw.get("tools") is not None
            )
            if has_prompt:
                prompt = self.prompt(row)
                prior = self.prompt(previous) if previous else None
                if (
                    prior is None
                    or prompt["system"] != prior["system"]
                    or prompt["tools"] != prior["tools"]
                ):
                    cells.append(
                        {
                            **base,
                            **({"turn": None} if previous is None else {}),
                            "sourceSeq": None,
                            "cellKey": "prompt",
                            "kind": "system",
                            "text": "指令与工具更新" if prior else "指令与工具目录",
                            "timeSeconds": 0,
                            "promptDetail": {"system": "", "tools": [], "config": {}},
                            **(
                                {"previousPromptDetail": {"system": "", "tools": [], "config": {}}}
                                if prior
                                else {}
                            ),
                        }
                    )
            for position, item in introduced:
                if (
                    not isinstance(item, dict)
                    or item.get("type") not in ("message", "input_message")
                    or item.get("role") in ("system", "developer")
                ):
                    continue
                assistant = item.get("role") == "assistant"
                text = message_text(item)
                context = not assistant and (
                    item.get("role") != "user"
                    or text.lstrip().startswith(
                        ("<environment_context>", "<turn_aborted>", "<codex_internal_context")
                    )
                )
                metadata = item.get("internal_chat_message_metadata_passthrough")
                if not isinstance(metadata, dict):
                    metadata = {}
                input_turn_id = metadata.get("turn_id")
                input_turn = (
                    self.turn_numbers.get(input_turn_id, turn)
                    if isinstance(input_turn_id, str)
                    else turn
                )
                current_user = (
                    not context
                    and not assistant
                    and (
                        input_turn_id == row.get("turnId")
                        if input_turn_id
                        else position == last_user
                    )
                )
                historical = assistant or not context and not current_user
                blocks = source_blocks(item, row["id"], f"input-{position}", metadata_only=True)
                attachments = [
                    block for block in blocks if "attachment" in block or "file" in block
                ]
                # Metadata counts are sufficient to paint the row without shipping a base64 image.
                source = (
                    text
                    if not attachments
                    else "\n".join(b["content"] for b in blocks if b["type"] == "text")
                )
                images = sum("attachment" in block for block in attachments)
                files = sum("file" in block for block in attachments)
                summary = " · ".join(
                    part
                    for part in [
                        f"图片 ×{images}" if images else "",
                        f"文件 ×{files}" if files else "",
                    ]
                    if part
                )
                cells.append(
                    {
                        **base,
                        "turn": input_turn,
                        "sourceSeq": None,
                        "cellKey": f"input:{position}",
                        "kind": "message" if assistant else "context" if context else "user",
                        **(
                            {"inputHistory": True, "step": 0, "group": "历史消息（请求输入）"}
                            if historical
                            else {}
                        ),
                        **(
                            {
                                "outputDetail": " ",
                                "isError": False,
                                "startedAt": None,
                                "assistantMetrics": {
                                    "timingRecorded": False,
                                    "usageProvided": False,
                                },
                            }
                            if assistant
                            else {"inputDetail": " "}
                        ),
                        "text": summary,
                        "previewMarkdown": source[:2048],
                        "opensTurn": current_user,
                        "timeSeconds": 0,
                        "messageSource": {
                            "role": item.get("role"),
                            "type": item.get("type"),
                            **({"kind": "request input"} if assistant else {}),
                        },
                        "sourceBlocks": [
                            {
                                **b,
                                "content": "",
                                **(
                                    {
                                        "attachment": {
                                            k: v
                                            for k, v in b["attachment"].items()
                                            if k != "recordedUrl"
                                        }
                                    }
                                    if b.get("attachment")
                                    else {}
                                ),
                            }
                            for b in attachments
                        ],
                    }
                )
            outputs = response.get("output_items", [])
            messages = [
                item for item in outputs if isinstance(item, dict) and item.get("type") == "message"
            ]
            reasoning = [
                item
                for item in outputs
                if isinstance(item, dict) and item.get("type") == "reasoning"
            ]
            returned_text = "\n\n".join(message_text(item) for item in messages)
            publicly_returned = "\n\n".join(public_reasoning(item) for item in reasoning)
            attachments = [
                block
                for item in messages
                for block in source_blocks(item, row["id"], "output", metadata_only=True)
                if "attachment" in block or "file" in block
            ]
            # Parent navigation must work before this assistant's body is hydrated.
            calls = [
                {
                    "type": "tool-call",
                    "content": "",
                    "callId": self.index.call_identity(row, item["call_id"]),
                    "toolName": item.get("name"),
                }
                for item in outputs
                if isinstance(item, dict)
                and item.get("type") in ("function_call", "custom_tool_call")
                and isinstance(item.get("call_id"), str)
            ]
            image_count = sum("attachment" in block for block in attachments)
            file_count = sum("file" in block for block in attachments)
            caption = " · ".join(
                part
                for part in [
                    f"图片 ×{image_count}" if image_count else "",
                    f"文件 ×{file_count}" if file_count else "",
                ]
                if part
            )
            tool_only = (
                not returned_text
                and not publicly_returned
                and any(
                    item.get("type") in ("function_call", "custom_tool_call")
                    for item in outputs
                    if isinstance(item, dict)
                )
            )
            facts = usage(response.get("token_usage")) or {}
            cells.append(
                {
                    **base,
                    "cellKey": "assistant",
                    "kind": "message",
                    "text": caption or ("（仅工具调用）" if tool_only else ""),
                    **({"requestOnly": True} if not outputs else {}),
                    **(
                        {"previewMarkdown": (returned_text or publicly_returned)[:2048]}
                        if returned_text or publicly_returned
                        else {}
                    ),
                    **({"sourceBlocks": [*attachments, *calls]} if attachments or calls else {}),
                    "outputDetail": " " if messages else "",
                    "thinkingDetail": " " if publicly_returned else "",
                    "assistantMetrics": {
                        "timingRecorded": True,
                        "stepStartTime": row["start"],
                        "firstTokenTime": None,
                        "completedTime": row.get("end"),
                        "usageProvided": bool(facts),
                        "outputTokens": facts.get("output"),
                    },
                    **{
                        target: facts[source]
                        for source, target in [
                            ("input", "input"),
                            ("cacheRead", "cacheRead"),
                            ("cacheWrite", "cacheWrite"),
                            ("output", "output"),
                            ("reasoning", "think"),
                        ]
                        if source in facts
                    },
                }
            )
        elif row.get("type") == "compaction":
            cells.append(
                {
                    **base,
                    "cellKey": "compaction",
                    "kind": "compacted",
                    "text": "上下文压缩",
                    "compactionApplied": row.get("compactionApplied") is True,
                    "outputDetail": " ",
                }
            )
        else:
            raw = self.index.payload(row.get("_input")) or {}
            program = row.get("type") == "code"
            output, output_items, result_error = result_view(
                self.index.payload(row.get("_output")), code=program
            )
            name = "functions.exec" if program else raw.get("tool_name", row.get("name", "unknown"))
            namespace = raw.get("tool_namespace")
            qualified = (
                f"{namespace}.{name}"
                if isinstance(namespace, str) and namespace and not name.startswith(namespace + ".")
                else name
            )
            invocation = raw.get("payload", raw)
            arguments = invocation.get("arguments") if isinstance(invocation, dict) else None
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except ValueError:
                    arguments = None
            native_program = (
                name in ("run_code", "cua_run_code")
                and isinstance(arguments, dict)
                and isinstance(arguments.get("code"), str)
            )
            bounded = output if isinstance(output, str) else bounded_json_preview(output)
            output_text = (
                bounded
                if isinstance(bounded, str)
                else json_text(bounded)
                if bounded is not None
                else ""
            )
            result_preview = preview(output_text, 160) + (
                "…" if bounded != output or len(output_text) > 160 else ""
            )
            cells.append(
                {
                    **base,
                    "cellKey": "tool",
                    "kind": row.get("kind", "tool"),
                    "toolName": name,
                    "isError": base["isError"] or result_error,
                    "qualifiedToolName": qualified,
                    "callId": self.index.call_identity(row, row.get("_modelCallId") or row["id"]),
                    **({"resultSeq": row["seq"]} if row.get("_output") else {}),
                    "text": f"{name} · {preview(row.get('_code') or row.get('_preview'), 100)}",
                    "inputDetail": " ",
                    "outputDetail": " " if row.get("_output") else "",
                    "schemaDetail": "",
                    "result": result_preview,
                    "programSource": " " if program or native_program else None,
                }
            )
            if program:
                cells[-1]["programDescription"] = preview(row.get("_code"), 120)
            elif native_program and isinstance(arguments, dict):
                cells[-1]["programDescription"] = preview(
                    arguments.get("description") or arguments["code"], 120
                )
        for slot, cell in enumerate(cells):
            cell.update(recordId=f"{row['id']}:{cell['cellKey']}", slot=slot)
            if cell.get("sourceSeq") is None:
                cell.pop("sourceSeq", None)
        self.cache[key] = cells
        while len(self.cache) > 1000:
            self.cache.popitem(last=False)
        return cells

    def page(self, limit=200, before=None, after=None, row_ids=None):
        self.index.refresh()
        with self.index.lock:
            eligible = [
                row
                for row in self.index.rows.values()
                if (before is None or row["seq"] < before)
                and (after is None or row["seq"] > after)
                and (row_ids is None or row["id"] in row_ids)
            ]
            rows = (
                eligible
                if row_ids is not None
                else eligible[-limit:]
                if after is None
                else eligible[:limit]
            )
            return {
                "cells": [cell for row in rows for cell in self.cells(row)],
                "requestNumbers": [
                    self.request_info(row)
                    for row in rows
                    if row.get("type") in ("request", "compaction")
                ],
                "rowIds": [row["id"] for row in rows],
                "hasEarlier": len(eligible) > len(rows),
                "beforeSeq": rows[0]["seq"] if rows else None,
                "afterSeq": rows[-1]["seq"] if rows else None,
            }

    def detail(self, row_id, cell_key):
        row = self.index.get_row(row_id)
        self.requests()
        key = (row_id, cell_key, row.get("_updated"), self.index.last_seq)
        if key in self.detail_cache:
            self.detail_cache.move_to_end(key)
            return self.detail_cache[key][0]
        data = self.build_detail(row_id, cell_key)
        size = len(json_text(data)) * 4
        if size < 16 * 1024 * 1024:
            self.detail_cache[key] = (data, size)
            self.detail_bytes += size
            while len(self.detail_cache) > 20 or self.detail_bytes > 32 * 1024 * 1024:
                _, (_, removed) = self.detail_cache.popitem(last=False)
                self.detail_bytes -= removed
        return data

    def build_detail(self, row_id, cell_key):
        row = self.index.get_row(row_id)
        template = next((cell for cell in self.cells(row) if cell["cellKey"] == cell_key), None)
        if template is None:
            raise TraceError("没有找到这条轨迹记录。", code="record_not_found")
        data = {**template, "detailsPending": False}
        if cell_key == "prompt":
            data["promptDetail"] = self.prompt(row)
            previous = self.previous_requests.get(row["id"])
            if previous:
                data["previousPromptDetail"] = self.prompt(previous)
        elif cell_key.startswith("input:"):
            position = int(cell_key.split(":")[1])
            item = self.index.payload(row["_request"])["input"][position]
            blocks = source_blocks(item, row["id"], f"input-{position}")
            origin = {"role": item.get("role"), "type": item.get("type")}
            if item.get("role") == "assistant":
                origin["kind"] = "request input"
            if "internal_chat_message_metadata_passthrough" in item:
                origin["metadata"] = item["internal_chat_message_metadata_passthrough"]
            field = "outputDetail" if item.get("role") == "assistant" else "inputDetail"
            data.update(
                {field: "\n\n".join(b["content"] for b in blocks if b["type"] == "text")},
                sourceBlocks=blocks,
                messageSource={**origin, "origin": "request_input"},
            )
        elif cell_key == "assistant":
            response = self.index.payload(row.get("_response")) or {}
            blocks = []
            thinking = []
            for item in response.get("output_items", []):
                if item.get("type") == "message":
                    blocks.extend(source_blocks(item, row["id"], "output"))
                elif item.get("type") == "reasoning":
                    thinking.append(public_reasoning(item))
                elif item.get("type") in ("function_call", "custom_tool_call"):
                    blocks.append(
                        {
                            "type": "tool-call",
                            "content": item.get("arguments", item.get("input", "")),
                            "callId": self.index.call_identity(row, item["call_id"])
                            if item.get("call_id")
                            else None,
                            "toolName": item.get("name"),
                        }
                    )
            data.update(
                outputDetail="\n\n".join(b["content"] for b in blocks if b["type"] == "text"),
                sourceBlocks=blocks,
                thinkingDetail="\n\n".join(thinking),
            )
        elif cell_key == "compaction":
            raw = json_text(self.index.payload(row.get("_response")))
            data.update(
                outputDetail=raw,
                sourceBlocks=[{"type": "text", "content": raw}],
                compactionInfo=compaction_info(self.index, row),
            )
        else:
            if row.get("type") == "code":
                data.update(inputDetail=row.get("_code", ""), programSource=row.get("_code", ""))
            else:
                data.pop("programSource", None)
                raw = self.index.payload(row.get("_input")) or {}
                payload = raw.get("payload", raw)
                args = payload.get("arguments", payload) if isinstance(payload, dict) else payload
                data["inputDetail"] = args if isinstance(args, str) else json_text(args)
            output, output_items, result_error = result_view(
                self.index.payload(row.get("_output")), code=row.get("type") == "code"
            )
            data["outputDetail"] = (
                output
                if isinstance(output, str)
                else json_text(output)
                if row.get("_output")
                else ""
            )
            data["isError"] = data["isError"] or result_error
            if output_items is not None:
                data["outputBlocks"] = source_blocks({"content": output_items}, row["id"], "result")
            _, _, _, request = self.location(row)
            if request.get("type") == "request":
                catalog = self.prompt(request)["tools"]
                schema = next(
                    (tool for tool in catalog if tool.get("name") == data.get("qualifiedToolName")),
                    None,
                )
                candidates = []
                if schema is None:
                    candidates = [
                        tool
                        for tool in catalog
                        if (
                            tool.get("name") == data.get("toolName")
                            or data.get("qualifiedToolName") == data.get("toolName")
                            and tool.get("sourceName") == data.get("toolName")
                        )
                    ]
                    if len(candidates) == 1:
                        schema = candidates[0]
                data["schemaDetail"] = json_text(schema) if schema else ""
                if schema is None and not candidates and row.get("kind") == "subtool":
                    declaration = recorded_tool_declaration(catalog, data.get("qualifiedToolName"))
                    if declaration:
                        data["schemaDetail"] = declaration
                        data["schemaSource"] = {
                            "kind": "recorded_tool_description",
                            "containerTool": "functions.exec",
                            "requestRowId": request["id"],
                        }
            if row.get("type") == "code":
                # Code cells are captured by the official JavaScript runtime event.
                data["programLanguage"] = "javascript"
        return data

    def search(self, query, rows, locale="zh"):
        terms = query.casefold().split()
        labels = GROUP_LABELS.get(locale, GROUP_LABELS["en"])
        matches = []
        for row_id in rows:
            row = self.index.get_row(row_id)
            for cell in self.cells(row):
                if cell.get("requestOnly"):
                    continue
                value = self.detail(row_id, cell["cellKey"])
                sources = [
                    f"turn {value['turn']}" if value["turn"] is not None else "between turns",
                    value["group"],
                    value["kind"],
                ]
                if value.get("inputHistory"):
                    sources.append(
                        "历史消息（请求输入）" if locale == "zh" else "history in request"
                    )
                if value.get("cellKey") == "compaction":
                    sources.append(labels["compaction"].format(seq=value["seq"]))
                elif isinstance(value.get("step"), int) and value["step"] > 0:
                    sources.append(labels["step"].format(step=value["step"]))
                if value["kind"] == "message":
                    sources.append("assistant")
                for key in (
                    "text",
                    "previewMarkdown",
                    "inputDetail",
                    "outputDetail",
                    "thinkingDetail",
                    "schemaDetail",
                    "result",
                    "resultPreviewMarkdown",
                    "callId",
                    "toolName",
                ):
                    if isinstance(value.get(key), str):
                        sources.append(value[key])
                for key in ("messageSource", "promptDetail", "previousPromptDetail"):
                    if key in value:
                        sources.append(json_text(value[key]))
                for block in [*value.get("sourceBlocks", []), *value.get("outputBlocks", [])]:
                    sources.extend(
                        str(block[key])
                        for key in ("type", "content", "callId", "toolName")
                        if block.get(key) is not None
                    )
                    if block.get("attachment", {}).get("name"):
                        sources.append(block["attachment"]["name"])
                    if block.get("file", {}).get("name"):
                        sources.append(block["file"]["name"])
                text = "\n".join(sources).casefold()
                if all(term in text for term in terms):
                    matches.append(cell["recordId"])
        return matches
