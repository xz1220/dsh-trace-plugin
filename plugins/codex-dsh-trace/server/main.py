#!/usr/bin/env python3
"""Local MCP Apps server and authenticated loopback preview for Codex Trace."""

from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from _version import VERSION
from store import Store, TraceError, identifier

PLUGIN = Path(__file__).resolve().parents[1]
URI = f"ui://rollout-viewer/viewer-{VERSION}.html"
LEGACY_URI = "ui://rollout-viewer/viewer.html"
STORE = Store()


def definition(
    name, title, properties=None, required=None, app=False, ui=False, entry=False, write=False
):
    meta: dict[str, Any] = {}
    if app:
        meta.update({"ui": {"visibility": ["app"]}, "openai/visibility": "private"})
    if ui:
        meta.setdefault("ui", {})["resourceUri"] = URI
        meta["openai/outputTemplate"] = URI
    if entry:
        meta["openai/ui"] = {"entrypoints": [{"type": "thread"}]}
    return {
        "name": name,
        "title": title,
        "description": title,
        "inputSchema": {
            "type": "object",
            "properties": properties or {},
            "required": required or [],
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": not write,
            "destructiveHint": False,
            "idempotentHint": not write,
            "openWorldHint": False,
        },
        "_meta": meta,
    }


STRING = {"type": "string"}
TRACE = {"traceId": STRING}
ROW = {**TRACE, "rowId": STRING}
CELL = {**ROW, "cellKey": STRING}
TOOLS = [
    definition(
        "list_rollout_traces", "List official rollout recordings", {"refresh": {"type": "boolean"}}
    ),
    definition(
        "show_rollout_trace",
        "Show an official rollout trace",
        {**TRACE, "threadId": STRING, "callId": STRING},
        ui=True,
    ),
    definition("open_rollout_viewer", "Codex Trace", app=True, ui=True, entry=True),
    definition(
        "get_rollout_binding",
        "Resolve the current chat recording without reading message bodies",
        {"threadId": STRING},
        ["threadId"],
        app=True,
    ),
    definition(
        "get_rollout_overview",
        "Read paged execution records",
        {
            **TRACE,
            "beforeSeq": {"type": "integer"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 500},
        },
        ["traceId"],
        app=True,
    ),
    definition(
        "get_rollout_delta",
        "Read new execution events",
        {**TRACE, "revision": STRING},
        ["traceId", "revision"],
        app=True,
    ),
    definition(
        "get_rollout_detail",
        "Inspect the selected request or tool",
        ROW,
        ["traceId", "rowId"],
        app=True,
    ),
    definition(
        "get_rollout_record",
        "Locate one execution record",
        {**ROW, "callId": STRING},
        ["traceId"],
        app=True,
    ),
    definition(
        "get_rollout_projection",
        "Read DSH trajectory records",
        {
            **TRACE,
            "rowIds": {"type": "array", "items": STRING, "maxItems": 500},
            "beforeSeq": {"type": "integer"},
            "afterSeq": {"type": "integer"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 500},
        },
        ["traceId"],
        app=True,
    ),
    definition(
        "get_rollout_cell_detail",
        "Inspect a DSH trajectory record",
        CELL,
        ["traceId", "rowId", "cellKey"],
        app=True,
    ),
    definition(
        "read_rollout_cell_text",
        "Read DSH record content in chunks",
        {
            **CELL,
            "field": STRING,
            "offset": {"type": "integer", "minimum": 0},
            "version": {"type": "integer", "minimum": 0},
            "snapshot": STRING,
        },
        ["traceId", "rowId", "cellKey", "field"],
        app=True,
    ),
    definition(
        "get_rollout_request_info",
        "Read complete request statistics",
        ROW,
        ["traceId", "rowId"],
        app=True,
    ),
    definition(
        "search_rollout_cells",
        "Search loaded trajectory bodies",
        {
            **TRACE,
            "query": STRING,
            "rowIds": {"type": "array", "items": STRING, "maxItems": 1000},
            "locale": {"type": "string", "enum": ["zh", "en", "ja", "es", "fr", "de", "ru", "pt"]},
        },
        ["traceId", "query", "rowIds"],
        app=True,
    ),
    definition(
        "read_rollout_text",
        "Read complete recorded content in chunks",
        {
            **ROW,
            "section": {
                "type": "string",
                "enum": [
                    "message",
                    "message_json",
                    "full_context",
                    "raw_request",
                    "response",
                    "tools",
                    "code",
                    "arguments",
                    "result",
                    "raw_result",
                    "runtime",
                ],
            },
            "snapshot": STRING,
            "itemIndex": {"type": "integer"},
            "offset": {"type": "integer", "minimum": 0},
        },
        ["traceId", "rowId", "section"],
        app=True,
    ),
    definition(
        "add_rollout_directory",
        "Add a local recording directory",
        {"path": STRING, "label": STRING},
        ["path"],
        app=True,
        write=True,
    ),
]


def call(name, args, metadata=None, *, store=None):
    store = STORE if store is None else store
    spec = next((x for x in TOOLS if x["name"] == name), None)
    if not spec or not isinstance(args, dict):
        raise TraceError("未知工具或无效参数。", code="invalid_tool")
    schema = spec["inputSchema"]
    if set(args) - set(schema["properties"]) or any(k not in args for k in schema["required"]):
        raise TraceError("工具参数不完整或包含未知字段。", code="invalid_tool_arguments")
    for key, value in args.items():
        field = schema["properties"][key]
        expected = field["type"]
        if expected == "string" and (not isinstance(value, str) or len(value) > 4096):
            raise TraceError(
                "字符串参数无效。", code="invalid_tool_arguments", params={"field": key}
            )
        if expected == "integer" and (
            type(value) is not int
            or value < field.get("minimum", 0)
            or value > field.get("maximum", 10**9)
        ):
            raise TraceError(
                "数值参数超出范围。", code="invalid_tool_arguments", params={"field": key}
            )
        if expected == "boolean" and type(value) is not bool:
            raise TraceError("布尔参数无效。", code="invalid_tool_arguments", params={"field": key})
        if expected == "array" and (
            not isinstance(value, list)
            or len(value) > field.get("maxItems", 1000)
            or any(not isinstance(item, str) or len(item) > 4096 for item in value)
        ):
            raise TraceError("列表参数无效。", code="invalid_tool_arguments", params={"field": key})
        if "enum" in field and value not in field["enum"]:
            raise TraceError(
                "参数不在支持的选项中。", code="invalid_tool_arguments", params={"field": key}
            )
    if name == "list_rollout_traces":
        return {**store.list(args.get("refresh", False)), "readerVersion": VERSION}
    if name == "open_rollout_viewer":
        meta = metadata if isinstance(metadata, dict) else {}
        first, second = meta.get("thread_id"), meta.get("threadId")
        thread_id = first or second
        if first and second and first != second:
            thread_id = None
        return store.open(thread_id=thread_id)
    if name == "get_rollout_binding":
        return store.binding(args["threadId"])
    if name == "show_rollout_trace":
        result = store.open(args.get("traceId"), args.get("threadId"))
        # Public model calls only launch the UI; detailed metadata stays in app-only calls.
        if result.get("view") != "trace":
            return result
        launch = {"view": "open", "trace": result["trace"]}
        if (
            result["trace"].get("isThreadAggregate")
            or args.get("threadId")
            and not args.get("traceId")
        ):
            launch["currentThreadId"] = result["currentThreadId"]
        if args.get("callId") is not None:
            launch["focusCallId"] = identifier(args["callId"])
        return launch
    if name == "get_rollout_overview":
        return store.index(args["traceId"]).overview(args.get("limit", 200), args.get("beforeSeq"))
    if name == "get_rollout_delta":
        return store.index(args["traceId"]).delta(args["revision"])
    if name == "get_rollout_detail":
        return store.details(args["traceId"], args["rowId"])
    if name == "get_rollout_record":
        if ("rowId" in args) == ("callId" in args):
            raise TraceError("请选择记录标识或调用标识之一。", code="invalid_locator")
        if "callId" in args:
            return {"row": store.locate_call(args["traceId"], args["callId"])}
        index = store.index(args["traceId"])
        return {"row": index.public_row(index.get_row(args["rowId"]))}
    if name == "get_rollout_projection":
        return store.projection(args["traceId"]).page(
            args.get("limit", 200), args.get("beforeSeq"), args.get("afterSeq"), args.get("rowIds")
        )
    if name == "get_rollout_cell_detail":
        return store.cell_detail(args["traceId"], args["rowId"], args["cellKey"])
    if name == "read_rollout_cell_text":
        return store.cell_text(
            args["traceId"],
            args["rowId"],
            args["cellKey"],
            args["field"],
            args.get("offset", 0),
            args.get("version"),
            args.get("snapshot"),
        )
    if name == "get_rollout_request_info":
        projector = store.projection(args["traceId"])
        with projector.index.lock:
            projector.index.prepare([projector.index.get_row(args["rowId"])])
            row = projector.index.get_row(args["rowId"])
            if row.get("type") not in ("request", "compaction"):
                raise TraceError("这条记录不是模型请求。", code="not_model_request")
            return {"request": projector.request_info(row, cumulative=True)}
    if name == "search_rollout_cells":
        projector = store.projection(args["traceId"])
        with projector.index.lock:
            return {
                "matches": projector.search(args["query"], args["rowIds"], args.get("locale", "zh"))
            }
    if name == "read_rollout_text":
        return store.text(
            args["traceId"],
            args["rowId"],
            args["section"],
            args.get("itemIndex"),
            args.get("offset", 0),
            args.get("snapshot"),
        )
    if name == "add_rollout_directory":
        return store.catalog.register(args["path"], args.get("label"))
    raise TraceError("未知工具。", code="invalid_tool")


def envelope(name, data):
    result = {
        "structuredContent": data,
        "content": [
            {
                "type": "text",
                "text": "Codex Trace is ready."
                if data.get("view")
                else "Local recording data loaded.",
            }
        ],
    }
    if name in ("show_rollout_trace", "open_rollout_viewer"):
        result["_meta"] = {"ui": {"resourceUri": URI}}
    return result


def error_data(exc):
    if isinstance(exc, TraceError):
        return {"error": str(exc), "errorCode": exc.code, "errorParams": exc.params}
    return {"error": "无法读取本地录制文件。", "errorCode": "local_read_failed", "errorParams": {}}


class RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def handle(method, params, *, store=None):
    if not isinstance(params, dict):
        raise RpcError(-32602, "Invalid params")
    if method == "initialize":
        requested = params.get("protocolVersion")
        return {
            "protocolVersion": requested
            if requested in ("2025-06-18", "2025-11-25")
            else "2025-06-18",
            "capabilities": {"tools": {}, "resources": {}},
            "serverInfo": {"name": "rollout-viewer", "version": VERSION},
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        try:
            return envelope(
                params.get("name"),
                call(
                    params.get("name"),
                    params.get("arguments", {}),
                    params.get("_meta"),
                    store=store,
                ),
            )
        except (TraceError, OSError) as exc:
            data = error_data(exc)
            return {
                "isError": True,
                "content": [{"type": "text", "text": data["error"]}],
                "structuredContent": data,
            }
    if method == "resources/list":
        return {
            "resources": [
                {"uri": URI, "name": "Codex Trace", "mimeType": "text/html;profile=mcp-app"}
            ]
        }
    if method in ("resources/templates/list", "prompts/list"):
        return {"resourceTemplates" if method.startswith("resources") else "prompts": []}
    if method == "resources/read":
        if params.get("uri") not in (URI, LEGACY_URI):
            raise RpcError(-32602, "Unknown resource URI")
        return {
            "contents": [
                {
                    "uri": params["uri"],
                    "mimeType": "text/html;profile=mcp-app",
                    "text": (PLUGIN / "assets/viewer.html").read_text(),
                    "_meta": {"ui": {"prefersBorder": True}},
                }
            ]
        }
    raise RpcError(-32601, "Method not found")


def stdio(*, store=None, input_stream=None, output_stream=None):
    input_stream = sys.stdin.buffer if input_stream is None else input_stream
    output_stream = sys.stdout if output_stream is None else output_stream
    output_lock = threading.Lock()

    def send(response):
        with output_lock:
            output_stream.write(json.dumps(response, ensure_ascii=False, allow_nan=False) + "\n")
            output_stream.flush()

    def failure(code, message, request_id=None):
        send({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})

    def process(request):
        request_id = request["id"]
        try:
            result = handle(request["method"], request.get("params", {}), store=store)
            send({"jsonrpc": "2.0", "id": request_id, "result": result})
        except RpcError as exc:
            failure(exc.code, str(exc), request_id)
        except Exception:
            failure(-32603, "Local viewer error", request_id)

    def reject_constant(value):
        raise ValueError("Non-finite JSON value: " + value)

    max_line = 2 * 1024 * 1024
    with ThreadPoolExecutor(max_workers=4) as pool:
        while True:
            line = input_stream.readline(max_line + 1)
            if not line:
                break
            if len(line) > max_line:
                while line and not line.endswith(b"\n"):
                    line = input_stream.readline(max_line + 1)
                failure(-32600, "Request too large")
                continue
            try:
                request = json.loads(line, parse_constant=reject_constant)
            except (ValueError, UnicodeError):
                failure(-32700, "Parse error")
                continue
            if (
                not isinstance(request, dict)
                or request.get("jsonrpc") != "2.0"
                or not isinstance(request.get("method"), str)
                or (
                    "id" in request
                    and request["id"] is not None
                    and type(request["id"]) not in (str, int)
                )
            ):
                failure(-32600, "Invalid Request")
                continue
            if "id" in request:
                pool.submit(process, request)


def create_preview_server(port, trace_id=None, *, store=None):
    from preview import create_preview_server as create

    store = STORE if store is None else store

    def dispatch(request):
        return envelope(
            request["name"],
            call(request["name"], request.get("arguments", {}), request.get("_meta"), store=store),
        )

    return create(port, trace_id, store=store, dispatch=dispatch, plugin=PLUGIN)


def preview_server(port, trace_id=None):
    with create_preview_server(port, trace_id) as server:
        print(json.dumps({"url": server.open_url, "port": server.server_port}), flush=True)
        server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--trace-id")
    parser.add_argument("--register")
    parser.add_argument("--label")
    parser.add_argument("--config-file")
    args = parser.parse_args()
    if args.config_file:
        STORE = Store(args.config_file)
    if args.register:
        print(json.dumps(STORE.catalog.register(args.register, args.label)))
    elif args.preview:
        preview_server(args.port, args.trace_id)
    else:
        stdio()
