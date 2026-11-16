"""Read-only recording facade coordinating catalog, indices, projections, and snapshots."""

from __future__ import annotations

import json
import os
import sys
import threading
import time as time  # Compatibility for callers patching store.time.monotonic.
from collections import OrderedDict
from typing import Any

from bundle_index import BundleIndex as BundleIndex
from bundle_index import clean_status as clean_status
from bundle_index import preview as preview
from catalog import Catalog as Catalog
from projection import Projection
from recorded_content import compaction_info as compaction_info
from recorded_content import item_meta as item_meta
from recorded_content import item_text as item_text
from recorded_content import unpack as unpack
from recording import CHUNK as CHUNK
from recording import ID_RE as ID_RE
from recording import MAX_LOG as MAX_LOG
from recording import MAX_PAYLOAD as MAX_PAYLOAD
from recording import PAYLOAD_RE as PAYLOAD_RE
from recording import SUPPORTED_SCHEMAS as SUPPORTED_SCHEMAS
from recording import TraceError as TraceError
from recording import TraceFormatError as TraceFormatError
from recording import identifier as identifier
from recording import read_json as read_json
from recording import safe_file as safe_file
from snapshots import Snapshots
from thread_index import ThreadIndex


class Store:
    def __init__(self, config_file=None):
        self.snapshots = Snapshots()
        self.catalog = Catalog(config_file)
        self.indexes = OrderedDict()
        self.thread_indexes = OrderedDict()
        self.lock = threading.RLock()

    def index(self, trace_id):
        if isinstance(trace_id, str) and trace_id.startswith("thread@"):
            return self.thread_index(trace_id[len("thread@") :])
        with self.lock:
            meta = self.catalog.find(trace_id=trace_id)
            if not meta:
                problem = next(
                    (item for item in self.catalog.issues if item.get("traceId") == trace_id), None
                )
                if problem:
                    raise TraceError(
                        problem["message"],
                        code=problem.get("errorCode", "trace_error"),
                        params=problem.get("errorParams"),
                    )
                raise TraceError("未找到该录制。请添加其所在目录。", code="recording_not_found")
            if trace_id not in self.indexes:
                self.indexes[trace_id] = BundleIndex(meta)
            self.indexes.move_to_end(trace_id)
            while len(self.indexes) > 4:
                self.indexes.popitem(last=False)
            return self.indexes[trace_id]

    def thread_index(self, thread_id):
        identifier(thread_id)
        with self.lock:
            if thread_id not in self.thread_indexes:
                self.thread_indexes[thread_id] = ThreadIndex(self, thread_id)
            self.thread_indexes.move_to_end(thread_id)
            while len(self.thread_indexes) > 2:
                self.thread_indexes.popitem(last=False)
            return self.thread_indexes[thread_id]

    def list(self, force=False):
        traces = self.catalog.list(force)
        return {
            "traces": [{k: v for k, v in x.items() if not k.startswith("_")} for x in traces[:100]],
            "moreAvailable": len(traces) > 100,
            "defaultRoot": str(self.catalog.default_root),
            "issues": self.catalog.issues[:20],
            "unreadableCount": len(self.catalog.issues),
            "recordingConfigured": bool(os.environ.get("CODEX_ROLLOUT_TRACE_ROOT")),
            "platform": sys.platform,
        }

    def binding(self, thread_id):
        index = self.thread_index(thread_id)
        index.refresh(force=True)
        meta = index.meta if index.sources else None
        return {
            "currentThreadId": thread_id,
            "trace": {k: v for k, v in meta.items() if not k.startswith("_")} if meta else None,
        }

    def open(self, trace_id=None, thread_id=None):
        if isinstance(trace_id, str) and trace_id.startswith("thread@"):
            selected = identifier(trace_id[len("thread@") :])
            if thread_id and thread_id != selected:
                raise TraceError("录制与聊天标识不一致。", code="recording_thread_mismatch")
            thread_id = selected
            trace_id = None
        if thread_id and not trace_id:
            index = self.thread_index(thread_id)
            index.refresh(force=True)
            if index.sources:
                return {"view": "trace", "currentThreadId": thread_id, **index.overview()}
            meta = None
        else:
            meta = self.catalog.find(trace_id, thread_id) if trace_id or thread_id else None
        if not meta:
            result = {"view": "select", "currentThreadId": thread_id, **self.list()}
            problem = next(
                (
                    item
                    for item in self.catalog.issues
                    if trace_id
                    and item.get("traceId") == trace_id
                    or thread_id
                    and item.get("threadId") == thread_id
                ),
                None,
            )
            if problem:
                result["unavailableReason"] = problem["message"]
                result["errorCode"] = problem.get("errorCode", "trace_error")
                result["errorParams"] = problem.get("errorParams", {})
            return result
        return {"view": "trace", "currentThreadId": thread_id, **self.index(meta["id"]).overview()}

    def projection(self, trace_id):
        index = self.index(trace_id)
        index.refresh()
        with index.lock:
            if index.projection is None:
                index.projection = Projection(index)
            return index.projection

    def locate_call(self, trace_id, call_id):
        identifier(call_id)
        index = self.index(trace_id)
        index.refresh()
        with index.lock:
            matches = [
                row
                for row in index.rows.values()
                if row.get("type") in ("tool", "code")
                and (
                    row.get("_modelCallId") == call_id
                    or index.call_identity(row, row.get("_modelCallId") or row["id"]) == call_id
                    or row["id"] == call_id
                    or row["id"] == "tool:" + call_id
                )
            ]
            if len(matches) != 1:
                raise TraceError(
                    "没有找到唯一对应的工具调用。请检查调用标识。", code="ambiguous_call_id"
                )
            row = matches[0]
            return {
                **index.public_row(row),
                "callId": index.call_identity(row, row.get("_modelCallId") or row["id"]),
            }

    def cell_detail(self, trace_id, row_id, cell_key):
        projector = self.projection(trace_id)
        with projector.index.lock:
            data = dict(projector.detail(row_id, cell_key))
            fields = {}
            texts = {}
            for key in (
                "inputDetail",
                "outputDetail",
                "thinkingDetail",
                "schemaDetail",
                "promptDetail",
                "previousPromptDetail",
                "sourceBlocks",
                "outputBlocks",
                "messageSource",
                "programSource",
            ):
                if key in data and data[key] is not None:
                    value = data.pop(key)
                    is_json = not isinstance(value, str)
                    text = json.dumps(value, ensure_ascii=False, indent=2) if is_json else value
                    fields[key] = {"totalChars": len(text), "json": is_json}
                    texts[key] = text
            snapshot = self.snapshots.create((trace_id, row_id, cell_key), texts)
            return {"cell": data, "fields": fields, "snapshot": snapshot}

    def cell_text(self, trace_id, row_id, cell_key, field, offset=0, version=None, snapshot=None):
        if snapshot is not None:
            return self.snapshots.page(snapshot, (trace_id, row_id, cell_key), field, offset)
        projector = self.projection(trace_id)
        with projector.index.lock:
            if version is not None and projector.index.get_row(row_id).get("_updated") != version:
                raise TraceError("记录已更新，请重新读取内容。", code="content_updated")
            data = projector.detail(row_id, cell_key)
            if field not in (
                "inputDetail",
                "outputDetail",
                "thinkingDetail",
                "schemaDetail",
                "promptDetail",
                "previousPromptDetail",
                "sourceBlocks",
                "outputBlocks",
                "messageSource",
                "programSource",
            ):
                raise TraceError(
                    "未知的轨迹内容字段。", code="invalid_content_field", params={"field": field}
                )
            value = data.get(field)
            if value is None:
                return {"text": "", "available": False, "totalChars": 0, "nextOffset": None}
            text = (
                value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
            )
            return self.text_page(text, offset)

    def details(self, trace_id, row_id):
        index = self.index(trace_id)
        with index.lock:
            row = index.get_row(row_id)
            data = {"row": index.public_row(row), "sections": []}
            if row.get("type") == "request":
                context = index.context(row_id)
                items = context["items"]
                response = index.payload(row.get("_response")) or {}
                data.update(
                    context={
                        k: v for k, v in context.items() if k not in ("items", "raw", "tools")
                    },
                    messages=[item_meta(x, i, row_id) for i, x in enumerate(items)],
                    usage=response.get("token_usage"),
                    options={
                        k: v
                        for k, v in context["raw"].items()
                        if k
                        in (
                            "model",
                            "reasoning",
                            "service_tier",
                            "stream",
                            "store",
                            "tool_choice",
                            "parallel_tool_calls",
                            "previous_response_id",
                        )
                    },
                    hasTopLevelTools=context["tools"] is not None,
                )
                data["sections"] = ["raw_request", "response", "tools"]
            elif row.get("type") in ("tool", "code"):
                result = unpack(index.payload(row.get("_output")), code=row.get("type") == "code")
                exit_code = result.get("exit_code") if isinstance(result, dict) else None
                data.update(
                    exitCode=exit_code,
                    parentId=row.get("parentId"),
                    childIds=[r["id"] for r in index.rows.values() if r.get("parentId") == row_id],
                    nextRequestId=self.next_request(index, row),
                )
                data["sections"] = [
                    "code" if row["type"] == "code" else "arguments",
                    "result",
                    "raw_result",
                    "runtime",
                ]
            elif row.get("type") == "compaction":
                data["compaction"] = compaction_info(index, row)
                data["sections"] = ["raw_request", "response"]
            else:
                data["sections"] = ["raw_request", "response"]
            return data

    @staticmethod
    def next_request(index, row):
        source = index.rows.get(row.get("parentId")) if row.get("kind") == "subtool" else row
        call_id = (source or row).get("_modelCallId")
        if not call_id:
            return None
        inspected = 0
        for candidate in index.rows.values():
            if (
                candidate.get("type") != "request"
                or candidate["seq"] <= row["seq"]
                or candidate["threadId"] != row["threadId"]
            ):
                continue
            inspected += 1
            if inspected > 128:
                break
            payload = index.payload(candidate.get("_request")) or {}
            if any(
                isinstance(item, dict)
                and item.get("call_id") == call_id
                and item.get("type") in ("custom_tool_call_output", "function_call_output")
                for item in payload.get("input", [])
            ):
                return candidate["id"]
        return None

    def text(self, trace_id, row_id, section, item_index=None, offset=0, snapshot=None):
        identity = (trace_id, row_id, section, item_index)
        if snapshot is not None:
            return self.snapshots.page(snapshot, identity, "text", offset)
        value: Any
        index = self.index(trace_id)
        with index.lock:
            row = index.get_row(row_id)
            cache_key = (row_id, row.get("_updated"), section, item_index)
            cached = index.text_cache.get(cache_key)
            if cached is not None:
                index.text_cache.move_to_end(cache_key)
                token = self.snapshots.create(identity, {"text": cached})
                return self.snapshots.page(token, identity, "text", offset)
            cacheable = True
            if section in ("message", "message_json", "full_context"):
                context = index.context(row_id)
                cacheable = context["complete"]
                if section == "full_context":
                    value = "\n\n".join(
                        f"[{item_meta(x, i, row_id)['role']}]\n{item_text(x['value'])}"
                        for i, x in enumerate(context["items"])
                    )
                else:
                    if not isinstance(item_index, int) or not 0 <= item_index < len(
                        context["items"]
                    ):
                        raise TraceError("无效的上下文项。", code="invalid_context_item")
                    item = context["items"][item_index]["value"]
                    value = (
                        item_text(item)
                        if section == "message"
                        else json.dumps(item, ensure_ascii=False, indent=2)
                    )
            elif section == "raw_request":
                value = index.payload(row.get("_request"))
            elif section == "response":
                value = index.payload(row.get("_response"))
            elif section == "tools":
                context = index.context(row_id)
                value = {
                    "top_level_tools": context["tools"],
                    "in_history_tool_declarations": [
                        x["value"]
                        for x in context["items"]
                        if isinstance(x["value"], dict)
                        and x["value"].get("type") == "additional_tools"
                    ],
                }
            elif section == "code":
                value = row.get("_code")
            elif section == "arguments":
                raw = index.payload(row.get("_input")) or {}
                payload = raw.get("payload", raw)
                value = payload.get("arguments", payload) if isinstance(payload, dict) else payload
            elif section in ("result", "raw_result"):
                raw = index.payload(row.get("_output"))
                value = "null" if raw is None and row.get("_output") else raw
                if section == "result":
                    parsed = unpack(raw, code=row.get("type") == "code")
                    if isinstance(parsed, dict):
                        value = parsed.get("output", parsed)
                    elif parsed is not None:
                        value = parsed
            elif section == "runtime":
                value = [index.payload(ref) for ref in row.get("_runtime", [])]
            else:
                raise TraceError(
                    "未知的详情类型。", code="invalid_content_field", params={"field": section}
                )
            if value is None:
                return {"text": "", "available": False, "totalChars": 0, "nextOffset": None}
            text = (
                value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
            )
            size = len(text) * 4
            if cacheable and size <= 16 * 1024 * 1024:
                index.text_cache[cache_key] = text
                index.text_cache_bytes += size
                while index.text_cache_bytes > 32 * 1024 * 1024 or len(index.text_cache) > 40:
                    _, evicted = index.text_cache.popitem(last=False)
                    index.text_cache_bytes -= len(evicted) * 4
            token = self.snapshots.create(identity, {"text": text})
            return self.snapshots.page(token, identity, "text", offset)

    @staticmethod
    def text_page(text, offset):
        if type(offset) is not int or offset < 0 or offset > len(text):
            raise TraceError("无效的文本分页位置。", code="invalid_text_offset")
        end = min(len(text), offset + CHUNK)
        return {
            "text": text[offset:end],
            "available": True,
            "totalChars": len(text),
            "offset": offset,
            "nextOffset": end if end < len(text) else None,
        }
