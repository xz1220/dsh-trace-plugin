"""Recorded message, tool result, and compaction content for inspection."""

import json

from bundle_index import preview


def item_text(value):
    if not isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, indent=2)
    content = value.get("content")
    if isinstance(content, list) and all(
        isinstance(x, dict) and isinstance(x.get("text"), str) for x in content
    ):
        return "\n\n".join(x["text"] for x in content)
    for key in ("text", "input", "arguments", "output"):
        if isinstance(value.get(key), str):
            return value[key]
    return json.dumps(value, ensure_ascii=False, indent=2)


def item_meta(entry, position, current):
    value = entry["value"]
    kind = value.get("type", "unknown") if isinstance(value, dict) else "unknown"
    role = value.get("role") if isinstance(value, dict) else None
    if not role:
        role = (
            "tool"
            if kind.endswith("_output")
            else "assistant"
            if kind in ("reasoning", "function_call", "custom_tool_call")
            else "context"
        )
    labels = {
        "message": "消息",
        "additional_tools": "工具声明",
        "custom_tool_call": "代码调用",
        "custom_tool_call_output": "代码返回值",
        "function_call": "工具调用",
        "function_call_output": "工具返回值",
        "reasoning": "推理项",
        "compaction": "压缩项",
    }
    return {
        "index": position,
        "type": kind,
        "role": role,
        "label": labels.get(kind, kind),
        "inherited": entry["requestId"] != current,
        "origin": entry["origin"],
        "sourceRequestId": entry["requestId"],
        "chars": len(item_text(value)),
        "preview": preview(item_text(value), 90) if kind == "message" else None,
        "hasEncryptedContent": isinstance(value, dict) and bool(value.get("encrypted_content")),
    }


def unpack(value, code=False):
    for _ in range(6):
        if isinstance(value, str):
            try:
                value = json.loads(value)
                continue
            except ValueError:
                return value
        if (
            isinstance(value, dict)
            and value.get("type") == "code_mode_response"
            and "value" in value
        ):
            value = value["value"]
        elif code and isinstance(value, dict) and set(value) == {"response"}:
            value = value["response"]
        else:
            break
    return value


def compaction_info(index, row):
    """Lazy, bounded facts about recorded context replacement, never decryption."""

    def counts(items):
        if not isinstance(items, list):
            return None
        roles: dict[str, int] = {}
        encrypted = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            if item.get("type") in ("message", "input_message") and isinstance(role, str):
                roles[role] = roles.get(role, 0) + 1
            if isinstance(item.get("encrypted_content"), str) and item["encrypted_content"]:
                encrypted += 1
        return {"items": len(items), "roles": roles, "encryptedItems": encrypted}

    def text_parts(value):
        if isinstance(value, str):
            return [value] if value else []
        if isinstance(value, list):
            return [part for item in value for part in text_parts(item)]
        if isinstance(value, dict) and isinstance(value.get("text"), str):
            return [value["text"]]
        return []

    checkpoint = index.payload(row.get("_checkpoint")) if row.get("_checkpoint") else None
    before = checkpoint.get("input_history") if isinstance(checkpoint, dict) else None
    after = checkpoint.get("replacement_history") if isinstance(checkpoint, dict) else None
    if not isinstance(before, list):
        request = index.payload(row.get("_request"))
        before = request.get("input") if isinstance(request, dict) else None
    response = index.payload(row.get("_response"))
    output = response.get("output_items") if isinstance(response, dict) else None
    parts = []
    for item in output if isinstance(output, list) else []:
        if isinstance(item, dict) and item.get("type") == "compaction":
            for field in ("summary", "text", "content"):
                parts.extend(text_parts(item.get(field)))
    summary = "\n\n".join(dict.fromkeys(parts))
    return {
        "applied": row.get("compactionApplied") is True,
        "installedAt": row.get("installedAt"),
        "before": counts(before),
        "after": counts(after),
        "output": counts(output),
        "readableSummary": summary[:4096],
        "readableSummaryChars": len(summary),
        "readableSummaryTruncated": len(summary) > 4096,
    }
