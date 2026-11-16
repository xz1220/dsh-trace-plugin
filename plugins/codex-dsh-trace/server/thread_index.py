"""A stable chronological view of official recordings for one exact chat root."""

from collections import OrderedDict
from typing import Any

from store import MAX_LOG, BundleIndex, TraceError, safe_file


def source_reference(value, source):
    if isinstance(value, dict):
        if "raw_payload_id" in value and "path" in value:
            return {**value, "_sourceTraceId": source}
        return {key: source_reference(item, source) for key, item in value.items()}
    if isinstance(value, list):
        return [source_reference(item, source) for item in value]
    return value


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
            if signatures == self.source_signatures and not issues_changed:
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
                index = self.store.index(source)
                index.refresh()
                with index.lock:
                    previous = self.sources.get(source)
                    if previous and previous["projectionRevision"] != index.projection_revision:
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
            ordered = sorted(
                ((source, row) for source, value in self.sources.items() for row in value["rows"]),
                key=lambda pair: (
                    pair[1]["start"],
                    self.sources[pair[0]]["meta"]["startedAt"] or 0,
                    pair[0],
                    pair[1]["seq"],
                ),
            )
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
            self.turns = dict(sorted(turns.items(), key=lambda pair: pair[1]["start"]))
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

    def response_row(self, response_id, current):
        if not response_id:
            return None
        local = self.local_responses.get((current.get("sourceTraceId"), response_id))
        if local:
            return local
        earlier = [
            key
            for key in self.shared_responses.get(response_id, [])
            if self.rows[key]["seq"] < current["seq"]
        ]
        return earlier[0] if len(earlier) == 1 else None

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
