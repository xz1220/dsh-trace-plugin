"""Incremental event indexing and continuation context for one recording bundle."""

from __future__ import annotations

import json
import os
import threading
from collections import OrderedDict

from recording import MAX_LOG, PAYLOAD_RE, TraceError, read_json, safe_file


def clean_status(value):
    return {
        "completed": "complete",
        "failed": "error",
        "cancelled": "cancelled",
        "interrupted": "cancelled",
        "aborted": "cancelled",
        "running": "running",
    }.get(value, value or "running")


def preview(value, size=120):
    source = "" if value is None else str(value)
    return " ".join(source[: max(2048, size * 8)].split())[:size]


class BundleIndex:
    def __init__(self, meta):
        self.meta = meta
        self.path = meta["_path"]
        self.lock = threading.RLock()
        self.metrics = {"logBytesRead": 0, "payloadReads": 0, "refreshes": 0}
        self.reset()

    def reset(self):
        self.offset = 0
        self.pending = b""
        self.signature = None
        self.last_seq = 0
        self.epoch = os.urandom(6).hex()
        self.projection_revision = 0
        self.rows = OrderedDict()
        self.threads = {}
        self.turns = {}
        self.cell_keys = {}
        self.responses = {}
        self.request_counter = 0
        self.tool_counter = 0
        self.code_counter = 0
        self.latest_requests = {}
        self.latest_request_seq = 0
        self.payload_cache = OrderedDict()
        self.payload_cache_size = 0
        self.context_cache = OrderedDict()
        self.text_cache = OrderedDict()
        self.text_cache_bytes = 0
        self.status = "running"
        self.latest_time = self.meta["startedAt"] or 0
        self.projection = None

    def refresh(self):
        with self.lock:
            path = safe_file(self.path, "trace.jsonl")
            stat = path.stat()
            sig = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
            if sig == self.signature:
                return
            if stat.st_size > MAX_LOG:
                raise TraceError(
                    "事件索引超过 256 MiB 上限，未返回不完整数据。",
                    code="recording_index_too_large",
                    params={"limitMiB": MAX_LOG // (1024 * 1024)},
                )
            if self.signature and (
                sig[:2] != self.signature[:2]
                or stat.st_size < self.offset
                or stat.st_size == self.offset
            ):
                self.reset()
            with path.open("rb") as stream:
                stream.seek(self.offset)
                chunk = stream.read(MAX_LOG + 1)
            self.metrics["logBytesRead"] += len(chunk)
            self.metrics["refreshes"] += 1
            self.offset += len(chunk)
            lines = (self.pending + chunk).split(b"\n")
            self.pending = lines.pop()
            try:
                for line in lines:
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    if not isinstance(event, dict) or not isinstance(event.get("payload"), dict):
                        raise TraceError("录制事件结构无效。", code="invalid_recording_events")
                    if (
                        type(event.get("schema_version")) is not int
                        or event.get("schema_version") != self.meta.get("schemaVersion", 1)
                        or event.get("seq") != self.last_seq + 1
                    ):
                        raise TraceError(
                            "事件版本或顺序不一致，请检查录制是否完整。",
                            code="invalid_recording_events",
                        )
                    self.apply(event)
                    self.last_seq = event["seq"]
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                self.reset()
                raise TraceError(
                    "录制事件格式或顺序不一致。", code="invalid_recording_events"
                ) from exc
            self.signature = sig

    def remember_refs(self, value):
        if isinstance(value, dict):
            if {"raw_payload_id", "path", "kind"} <= value.keys():
                if not isinstance(value["path"], str) or not PAYLOAD_RE.fullmatch(value["path"]):
                    raise TraceError(
                        "录制中的 payload 路径不合法。", code="invalid_payload_reference"
                    )
            for item in value.values():
                self.remember_refs(item)
        elif isinstance(value, list):
            for item in value:
                self.remember_refs(item)

    def row(self, key, event, **values):
        if key not in self.rows:
            self.rows[key] = {
                "id": key,
                "seq": event["seq"],
                "start": event["wall_time_unix_ms"],
                "end": None,
                "status": "running",
                "threadId": event.get("thread_id") or self.meta["threadId"],
                "turnId": event.get("codex_turn_id"),
                "parentId": None,
            }
        row = self.rows[key]
        row.update(values)
        row["_updated"] = event["seq"]
        return row

    def apply(self, event):
        payload = event["payload"]
        kind = payload["type"]
        now = event["wall_time_unix_ms"]
        self.latest_time = max(self.latest_time, now)
        self.remember_refs(payload)
        thread = event.get("thread_id") or payload.get("thread_id") or self.meta["threadId"]
        if kind == "thread_started":
            identity = payload["thread_id"]
            label = payload.get("agent_path", identity[:8])
            if self.threads.get(identity) != label and any(
                row["threadId"] == identity for row in self.rows.values()
            ):
                self.projection_revision = event["seq"]
            self.threads[payload["thread_id"]] = payload.get("agent_path", payload["thread_id"][:8])
        elif kind == "codex_turn_started":
            turn_id = payload["codex_turn_id"]
            if any(row.get("turnId") == turn_id for row in self.rows.values()):
                self.projection_revision = event["seq"]
            self.turns[turn_id] = {"start": now, "threadId": thread}
        elif kind == "inference_started":
            self.latest_request_seq = event["seq"]
            key = "request:" + payload["inference_call_id"]
            self.request_counter += 1
            number = self.request_counter
            self.row(
                key,
                event,
                type="request",
                kind="message",
                name=f"请求 #{number}",
                model=payload.get("model"),
                provider=payload.get("provider_name"),
                threadId=payload.get("thread_id", thread),
                turnId=payload.get("codex_turn_id"),
                _request=payload["request_payload"],
                _response=None,
                responseId=None,
            )
            self.latest_requests[payload.get("thread_id", thread)] = key
        elif kind in ("inference_completed", "inference_failed", "inference_cancelled"):
            key = "request:" + payload["inference_call_id"]
            original = self.rows.get(key)
            if original and original["seq"] < self.latest_request_seq:
                self.projection_revision = event["seq"]
            self.context_cache.clear()
            self.text_cache.clear()
            self.text_cache_bytes = 0
            self.row(
                key,
                event,
                end=now,
                status={
                    "inference_completed": "complete",
                    "inference_failed": "error",
                    "inference_cancelled": "cancelled",
                }[kind],
                _response=payload.get("response_payload")
                or payload.get("partial_response_payload"),
                responseId=payload.get("response_id"),
                _error=payload.get("error") or payload.get("reason"),
            )
            if payload.get("response_id"):
                self.responses[payload["response_id"]] = key
        elif kind == "code_cell_started":
            self.code_counter += 1
            key = "cell:" + thread + ":" + payload["runtime_cell_id"]
            self.cell_keys[(thread, payload["runtime_cell_id"])] = key
            parent = self.latest_requests.get(thread)
            self.row(
                key,
                event,
                type="code",
                kind="tool",
                name="functions.exec",
                parentId=parent,
                _code=payload.get("source_js", ""),
                _output=None,
                _runtimeCell=payload["runtime_cell_id"],
                _modelCallId=payload.get("model_visible_call_id"),
            )
        elif kind in ("code_cell_ended", "code_cell_initial_response"):
            key = self.cell_keys.get((thread, payload["runtime_cell_id"]))
            if key:
                values = {"_output": payload.get("response_payload")}
                if kind == "code_cell_ended":
                    values.update(end=now, status=clean_status(payload.get("status")))
                self.row(key, event, **values)
        elif kind == "tool_call_started":
            self.tool_counter += 1
            requester = payload.get("requester", {})
            parent = self.cell_keys.get((thread, requester.get("runtime_cell_id")))
            if not parent:
                parent = self.latest_requests.get(thread)
            self.row(
                "tool:" + payload["tool_call_id"],
                event,
                type="tool",
                kind="subtool" if requester.get("type") == "code_cell" else "tool",
                name=preview(
                    payload.get("summary", {}).get("label") or payload.get("kind", {}).get("type"),
                    90,
                ),
                parentId=parent,
                _input=payload.get("invocation_payload"),
                _output=None,
                _runtime=[],
                _preview=payload.get("summary", {}).get("input_preview"),
                _modelCallId=payload.get("model_visible_call_id"),
            )
        elif kind == "tool_call_ended":
            self.row(
                "tool:" + payload["tool_call_id"],
                event,
                end=now,
                status=clean_status(payload.get("status")),
                _output=payload.get("result_payload"),
            )
        elif kind in ("tool_call_runtime_started", "tool_call_runtime_ended"):
            row = self.rows.get("tool:" + payload["tool_call_id"])
            if row and payload.get("runtime_payload"):
                row.setdefault("_runtime", []).append(payload["runtime_payload"])
                row["_updated"] = event["seq"]
        elif kind == "rollout_ended":
            self.status = clean_status(payload.get("status"))
        elif kind == "compaction_request_started":
            self.request_counter += 1
            key = "compaction:" + payload.get("compaction_request_id", str(event["seq"]))
            self.row(
                key,
                event,
                type="compaction",
                kind="context",
                name="上下文压缩",
                threadId=payload.get("thread_id", thread),
                turnId=payload.get("codex_turn_id"),
                model=payload.get("model"),
                provider=payload.get("provider_name"),
                _request=payload.get("request_payload"),
                _response=None,
                _compactionId=payload.get("compaction_id"),
            )
        elif kind in ("compaction_request_completed", "compaction_request_failed"):
            key = "compaction:" + payload.get("compaction_request_id", "")
            if key in self.rows:
                self.row(
                    key,
                    event,
                    end=now,
                    status="error" if kind.endswith("failed") else "complete",
                    _response=payload.get("response_payload"),
                    _error=payload.get("error"),
                )
        elif kind == "compaction_installed":
            compaction_id = payload.get("compaction_id")
            checkpoint = payload.get("checkpoint_payload")
            if isinstance(compaction_id, str) and compaction_id and isinstance(checkpoint, dict):
                candidates = [
                    row
                    for row in self.rows.values()
                    if row.get("type") == "compaction"
                    and row.get("status") == "complete"
                    and row.get("_compactionId") == compaction_id
                    and row.get("threadId") == thread
                ]
                if len(candidates) == 1 and not candidates[0].get("compactionApplied"):
                    self.row(
                        candidates[0]["id"],
                        event,
                        compactionApplied=True,
                        installedAt=now,
                        _checkpoint=checkpoint,
                    )

    def public_row(self, row):
        data = {k: v for k, v in row.items() if not k.startswith("_")}
        data["version"] = row["_updated"]
        data["threadLabel"] = self.threads.get(row["threadId"], row["threadId"][:8])
        data["durationMs"] = (
            max(0, row["end"] - row["start"]) if row.get("end") is not None else None
        )
        data["error"] = row.get("status") == "error"
        snippet = row.get("_preview")
        if isinstance(snippet, str):
            try:
                parsed = json.loads(snippet)
                snippet = (
                    parsed.get("cmd", parsed.get("command", snippet))
                    if isinstance(parsed, dict)
                    else snippet
                )
            except ValueError:
                pass
            data["summary"] = preview(snippet, 180)
        return data

    def overview(self, limit=200, before=None):
        self.refresh()
        with self.lock:
            all_rows = list(self.rows.values())
            eligible = [r for r in all_rows if before is None or r["seq"] < before]
            rows = eligible[-limit:]
            return {
                "trace": {k: v for k, v in self.meta.items() if not k.startswith("_")},
                "revision": f"{self.epoch}:{self.last_seq}",
                "projectionRevision": self.projection_revision,
                "status": self.status,
                "origin": self.meta["startedAt"],
                "latestTime": self.latest_time,
                "totalRows": len(all_rows),
                "requestCount": self.request_counter,
                "toolCount": self.tool_counter,
                "codeCellCount": self.code_counter,
                "threads": [{"id": k, "label": v} for k, v in self.threads.items()],
                "rows": [self.public_row(r) for r in rows],
                "hasEarlier": len(eligible) > len(rows),
                "beforeSeq": rows[0]["seq"] if rows else None,
            }

    def delta(self, revision):
        self.refresh()
        with self.lock:
            try:
                epoch, seq = revision.split(":")
                seq = int(seq)
            except (AttributeError, ValueError):
                epoch, seq = "", -1
            if epoch != self.epoch or seq > self.last_seq or seq < self.projection_revision:
                return {"resync": True}
            if seq == self.last_seq:
                return {
                    "revision": revision,
                    "status": self.status,
                    "unchanged": True,
                    "latestTime": self.latest_time,
                    "totalRows": len(self.rows),
                    "rows": [],
                }
            changed = [r for r in self.rows.values() if r.get("_updated", 0) > seq]
            if len(changed) > 400:
                return {"resync": True}
            return {
                "revision": f"{self.epoch}:{self.last_seq}",
                "status": self.status,
                "unchanged": seq == self.last_seq,
                "latestTime": self.latest_time,
                "requestCount": self.request_counter,
                "toolCount": self.tool_counter,
                "codeCellCount": self.code_counter,
                "threads": [{"id": k, "label": v} for k, v in self.threads.items()],
                "totalRows": len(self.rows),
                "rows": [self.public_row(r) for r in changed],
            }

    def payload(self, ref):
        if not ref:
            return None
        name = ref.get("path", "")
        if not PAYLOAD_RE.fullmatch(name):
            raise TraceError("无效的 payload 引用。", code="invalid_payload_reference")
        path = safe_file(self.path, name)
        stat = path.stat()
        key = (name, stat.st_mtime_ns, stat.st_size)
        if key in self.payload_cache:
            self.payload_cache.move_to_end(key)
            return self.payload_cache[key][0]
        data = read_json(path)
        self.metrics["payloadReads"] += 1
        if stat.st_size <= 16 * 1024 * 1024:
            self.payload_cache[key] = (data, stat.st_size)
            self.payload_cache_size += stat.st_size
            while self.payload_cache and self.payload_cache_size > 32 * 1024 * 1024:
                _, (_, size) = self.payload_cache.popitem(last=False)
                self.payload_cache_size -= size
        return data

    def get_row(self, row_id):
        self.refresh()
        row = self.rows.get(row_id)
        if not row:
            raise TraceError("没有找到这条执行记录。", code="record_not_found")
        return row

    def response_row(self, response_id, current):
        return self.responses.get(response_id)

    def call_identity(self, row, call_id):
        return call_id

    def context(self, row_id):
        # Iterative reconstruction avoids recursion and intermediate full copies.
        row = self.get_row(row_id)
        if row.get("type") != "request":
            raise TraceError("这条记录不是模型请求。", code="not_model_request")
        if row_id in self.context_cache:
            self.context_cache.move_to_end(row_id)
            return self.context_cache[row_id]
        seen = set()
        chain = []
        cursor = row_id
        base = None
        complete, missing = True, None
        while cursor is not None:
            if cursor in seen:
                raise TraceError("响应链包含循环。", code="response_chain_cycle")
            seen.add(cursor)
            if cursor in self.context_cache:
                base = self.context_cache[cursor]
                break
            current = self.rows.get(cursor)
            if not current or current.get("type") != "request":
                complete, missing = False, cursor
                break
            raw = self.payload(current.get("_request"))
            if not isinstance(raw, dict) or not isinstance(raw.get("input"), list):
                raise TraceError("原始请求缺少 input 数组。", code="invalid_request_input")
            chain.append((cursor, current, raw))
            previous = raw.get("previous_response_id")
            if not previous:
                break
            cursor = self.response_row(previous, current)
            if cursor is None:
                complete, missing = False, previous
                break
        items = list(base["items"]) if base else []
        tools = base["tools"] if base else None
        for request_id, current, raw in reversed(chain):
            previous = raw.get("previous_response_id")
            parent_id = self.response_row(previous, current) if previous else None
            if parent_id is not None:
                output = self.payload(self.rows[parent_id].get("_response")) or {}
                if not isinstance(output.get("output_items"), list):
                    complete, missing = False, previous
                else:
                    items.extend(
                        {"value": value, "requestId": parent_id, "origin": "response"}
                        for value in output["output_items"]
                    )
            if raw.get("tools") is not None:
                tools = raw["tools"]
            items.extend(
                {"value": value, "requestId": request_id, "origin": "input"}
                for value in raw["input"]
            )
        raw = chain[0][2]
        context = {
            "items": items,
            "complete": complete,
            "missing": missing,
            "tools": tools,
            "incremental": bool(raw.get("previous_response_id")),
            "previousRequestId": self.response_row(raw.get("previous_response_id"), row),
            "raw": raw,
        }
        if complete:
            self.context_cache[row_id] = context
            while len(self.context_cache) > 16:
                self.context_cache.popitem(last=False)
        return context
