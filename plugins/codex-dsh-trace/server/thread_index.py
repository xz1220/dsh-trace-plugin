"""A stable chronological view of official recordings for one exact chat root."""

from collections import OrderedDict
from heapq import heappop, heappush
from typing import Any

from bundle_index import BundleIndex
from recording import MAX_LOG, TraceError, safe_file


def source_reference(value, source):
    if isinstance(value, dict):
        if "raw_payload_id" in value and "path" in value:
            return {**value, "_sourceTraceId": source}
        return {key: source_reference(item, source) for key, item in value.items()}
    if isinstance(value, list):
        return [source_reference(item, source) for item in value]
    return value


def ordered_records(sources, previous_responses):
    """Recorded source order is hard; wall time is only the interleaving preference."""
    records, priorities, base_edges = {}, {}, set()
    local: dict[tuple[str, str], list[str]] = {}
    shared: dict[str, list[str]] = {}
    for source, capture in sources.items():
        floor = capture["meta"]["startedAt"] or 0
        before = None
        for row in capture["rows"]:
            key = source + ":" + row["id"]
            records[key] = (source, row)
            # This key is never written back as a recorded timestamp or duration.
            floor = max(floor, row["start"])
            priorities[key] = (floor, capture["meta"]["startedAt"] or 0, source, row["seq"])
            if before is not None:
                base_edges.add((before, key))
            before = key
            if row.get("responseId"):
                local.setdefault((source, row["responseId"]), []).append(key)
                shared.setdefault(row["responseId"], []).append(key)
    links = {}
    for key, previous in previous_responses.items():
        if key not in records or not previous:
            continue
        candidates = local.get((records[key][0], previous), shared.get(previous, []))
        if len(candidates) == 1:
            links[key] = candidates[0]

    def sort(edges):
        children: dict[str, list[str]] = {key: [] for key in records}
        incoming = dict.fromkeys(records, 0)
        for parent, child in edges:
            children[parent].append(child)
            incoming[child] += 1
        ready: list[tuple[Any, str]] = []
        for key, count in incoming.items():
            if not count:
                heappush(ready, (priorities[key], key))
        result = []
        while ready:
            _, key = heappop(ready)
            result.append(key)
            for child in children[key]:
                incoming[child] -= 1
                if not incoming[child]:
                    heappush(ready, (priorities[child], child))
        return result, {key for key, count in incoming.items() if count}

    causal_edges = {(parent, child) for child, parent in links.items()}
    result, blocked = sort(base_edges | causal_edges)
    if blocked:
        # Reject conflicting/cyclic references, never reorder a source to fit them.
        links = {
            child: parent
            for child, parent in links.items()
            if not (child in blocked and parent in blocked and (parent, child) not in base_edges)
        }
        result, _ = sort(base_edges | {(parent, child) for child, parent in links.items()})
    return [records[key] for key in result], links


class ThreadIndex(BundleIndex):
    def __init__(self, store, thread_id):
        self.store = store
        self.thread_id = thread_id
        super().__init__(
            {
                "id": "thread@" + thread_id,
                "threadId": thread_id,
                "label": "当前聊天",
                "startedAt": None,
                "isThreadAggregate": True,
                "recordingCount": 0,
                "_path": store.catalog.default_root,
            }
        )
        self.sources = {}
        self.source_signatures = {}
        self.local_responses = {}
        self.shared_responses = {}
        self.previous_responses = {}
        self.response_links = {}
        self.order_dirty = False

    def refresh(self, force=False):
        with self.lock:
            candidates = [
                meta
                for meta in self.store.catalog.list(force)
                if meta["threadId"] == self.thread_id
            ]
            issues = [
                issue
                for issue in self.store.catalog.issues
                if issue.get("threadId") == self.thread_id
            ]
            issues_changed = issues != self.meta.get("issues", [])
            self.meta.update(issues=issues, incomplete=bool(issues))
            metas = []
            signatures = {}
            for meta in candidates:
                path = meta["_path"] / "trace.jsonl"
                if meta["id"] not in self.sources and not path.exists() and not path.is_symlink():
                    continue
                stat = safe_file(meta["_path"], "trace.jsonl").stat()
                signatures[meta["id"]] = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
                metas.append(meta)
            if sum(signature[2] for signature in signatures.values()) > MAX_LOG:
                raise TraceError(
                    "当前聊天的录制总索引超过 256 MiB 上限，未返回不完整数据。",
                    code="recording_index_too_large",
                    params={"limitMiB": MAX_LOG // (1024 * 1024)},
                )
            if signatures == self.source_signatures and not issues_changed and not self.order_dirty:
                return
            reset = bool(set(self.sources) - set(signatures))
            projection_changed = False
            for meta in metas:
                source = meta["id"]
                before = self.source_signatures.get(source)
                after = signatures[source]
                if before == after:
                    continue
                if before and (before[:2] != after[:2] or after[2] <= before[2]):
                    reset = True
                    self.previous_responses = {
                        key: value
                        for key, value in self.previous_responses.items()
                        if not key.startswith(source + ":")
                    }
                index = self.store.index(source)
                index.refresh()
                with index.lock:
                    previous = self.sources.get(source)
                    if previous and previous["projectionRevision"] != index.projection_revision:
                        projection_changed = True
                    for original in index.rows.values():
                        old = self.rows.get(source + ":" + original["id"])
                        if (
                            old
                            and original.get("type") == "request"
                            and old.get("_sourceVersion") != original.get("_updated")
                            and old["seq"] < self.latest_request_seq
                        ):
                            projection_changed = True
                    self.sources[source] = {
                        "meta": meta,
                        "rows": [dict(row) for row in index.rows.values()],
                        "turns": dict(index.turns),
                        "threads": dict(index.threads),
                        "status": index.status,
                        "latestTime": index.latest_time,
                        "projectionRevision": index.projection_revision,
                    }
            self.sources = {key: value for key, value in self.sources.items() if key in signatures}
            known_rows = {
                source + ":" + row["id"]
                for source, value in self.sources.items()
                for row in value["rows"]
            }
            self.previous_responses = {
                key: value for key, value in self.previous_responses.items() if key in known_rows
            }
            old_links = self.response_links
            ordered, self.response_links = ordered_records(self.sources, self.previous_responses)
            if any(self.response_links.get(key) != parent for key, parent in old_links.items()):
                projection_changed = True
            self.order_dirty = False
            keys = [source + ":" + row["id"] for source, row in ordered]
            old_threads = self.threads
            old_turns = self.turns
            old_keys = list(self.rows)
            if old_keys != keys[: len(old_keys)]:
                reset = True
            if reset:
                super().reset()
            self.last_seq += 1
            revision = self.last_seq
            old_rows = self.rows
            new_rows = OrderedDict()
            self.local_responses = {}
            self.shared_responses = {}
            for seq, (source, original) in enumerate(ordered, 1):
                key = source + ":" + original["id"]
                old = old_rows.get(key)
                if old and old.get("_sourceVersion") == original.get("_updated"):
                    row = old
                else:
                    row = source_reference(original, source)
                    row.update(
                        id=key,
                        seq=seq,
                        _updated=revision,
                        _sourceVersion=original.get("_updated"),
                        sourceTraceId=source,
                        sourceRowId=original["id"],
                        sourceEventSeq=original["seq"],
                    )
                    if original.get("parentId"):
                        row["parentId"] = source + ":" + original["parentId"]
                new_rows[key] = row
                if row.get("responseId"):
                    self.local_responses[(source, row["responseId"])] = key
                    self.shared_responses.setdefault(row["responseId"], []).append(key)
            self.rows = new_rows
            self.threads = {}
            turns: dict[str, dict[str, Any]] = {}
            for value in self.sources.values():
                self.threads.update(value["threads"])
                for key, turn in value["turns"].items():
                    if key not in turns or turn["start"] < turns[key]["start"]:
                        turns[key] = turn
            observed_turns = dict.fromkeys(
                row.get("turnId") for row in self.rows.values() if row.get("turnId") in turns
            )
            remaining_turns = sorted(
                (key for key in turns if key not in observed_turns),
                key=lambda key: (turns[key]["start"], key),
            )
            self.turns = {key: turns[key] for key in [*observed_turns, *remaining_turns]}
            if (
                issues_changed
                or projection_changed
                or any(
                    old_threads.get(thread) != label
                    and any(row["threadId"] == thread for row in old_rows.values())
                    for thread, label in self.threads.items()
                )
                or any(
                    old_turns.get(turn) != value
                    and any(row.get("turnId") == turn for row in old_rows.values())
                    for turn, value in self.turns.items()
                )
            ):
                self.projection_revision = revision
            self.request_counter = sum(
                row.get("type") in ("request", "compaction") for row in self.rows.values()
            )
            self.latest_request_seq = max(
                (row["seq"] for row in self.rows.values() if row.get("type") == "request"),
                default=0,
            )
            self.tool_counter = sum(row.get("type") == "tool" for row in self.rows.values())
            self.code_counter = sum(row.get("type") == "code" for row in self.rows.values())
            self.context_cache.clear()
            self.text_cache.clear()
            self.text_cache_bytes = 0
            recording_ids = sorted(
                self.sources,
                key=lambda source: (self.sources[source]["meta"]["startedAt"] or 0, source),
            )
            self.meta.update(recordingCount=len(self.sources), recordingIds=recording_ids)
            if self.sources:
                latest = max(
                    self.sources.values(), key=lambda value: value["meta"]["startedAt"] or 0
                )
                versions = sorted(
                    {value["meta"]["schemaVersion"] for value in self.sources.values()}
                )
                self.meta.update(
                    startedAt=min(
                        value["meta"]["startedAt"] or 0 for value in self.sources.values()
                    ),
                    schemaVersion=versions[0] if len(versions) == 1 else None,
                    schemaVersions=versions,
                )
                self.status = latest["status"]
                self.latest_time = max(value["latestTime"] for value in self.sources.values())
            else:
                self.meta.update(startedAt=None, schemaVersion=None, schemaVersions=[])
                self.status = "complete"
                self.latest_time = 0
            self.source_signatures = signatures

    def payload(self, ref):
        if not ref:
            return None
        source = ref.get("_sourceTraceId")
        if source not in self.sources:
            raise TraceError("未找到这条记录对应的原始录制。", code="recording_not_found")
        return self.store.index(source).payload(ref)

    def prepare(self, rows, *, ancestors=False):
        """Learn only requested contexts, then resync if their explicit causes reorder rows."""
        self.refresh()
        with self.lock:
            epoch = self.epoch
            pending = [(row["id"], ancestors) for row in rows]
            seen: dict[str, bool] = {}
            while pending:
                key, follow = pending.pop()
                if key in seen and (not follow or seen[key]):
                    continue
                seen[key] = follow
                row = self.rows.get(key)
                if not row:
                    continue
                if row.get("type") != "request":
                    if row.get("parentId"):
                        pending.append((row["parentId"], follow))
                    continue
                if key not in self.previous_responses:
                    raw = self.payload(row.get("_request"))
                    previous = raw.get("previous_response_id") if isinstance(raw, dict) else None
                    self.previous_responses[key] = previous if isinstance(previous, str) else None
                    if self.previous_responses[key]:
                        self.order_dirty = True
                previous = self.previous_responses[key]
                if previous:
                    local = self.local_responses.get((row.get("sourceTraceId"), previous))
                    candidates = [local] if local else self.shared_responses.get(previous, [])
                    if len(candidates) == 1:
                        parent = candidates[0]
                        # A local predecessor is already ordered by the recording.
                        # Full context and cross-capture references need the chain;
                        # painting one page must not eagerly read an entire bundle.
                        if follow or self.rows[parent].get("sourceTraceId") != row.get(
                            "sourceTraceId"
                        ):
                            pending.append((parent, True))
            if self.order_dirty:
                self.refresh()
            return epoch != self.epoch

    def context(self, row_id):
        self.prepare([self.get_row(row_id)], ancestors=True)
        return super().context(row_id)

    def response_row(self, response_id, current):
        if self.previous_responses.get(current["id"]) != response_id:
            return None
        return self.response_links.get(current["id"])

    def call_identity(self, row, call_id):
        prefix = row["sourceTraceId"] + ":"
        return call_id if call_id.startswith(prefix) else prefix + call_id

    def delta(self, revision):
        value = super().delta(revision)
        if not value.get("resync"):
            value["trace"] = {
                key: item for key, item in self.meta.items() if not key.startswith("_")
            }
        return value
