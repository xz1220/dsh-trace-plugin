"""Discover and register recording roots without reading message payloads."""

import json
import os
import threading
import time
from pathlib import Path

from recording import (
    ID_RE,
    SUPPORTED_SCHEMAS,
    TraceError,
    TraceFormatError,
    identifier,
    read_json,
    safe_file,
)


class Catalog:
    def __init__(self, config_file=None):
        codex = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        self.config_file = (
            Path(config_file) if config_file else codex / "rollout-viewer/config.json"
        )
        self.default_root = codex / "rollout-traces"
        self.lock = threading.RLock()
        self.cache = {}
        self.issues = []
        self.last_scan = None

    def config(self):
        if not self.config_file.exists():
            return {"roots": [], "labels": {}}
        data = read_json(self.config_file, 1024 * 1024)
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("roots", []), list)
            or any(not isinstance(root, str) or not root for root in data.get("roots", []))
            or not isinstance(data.get("labels", {}), dict)
            or any(not isinstance(label, str) for label in data.get("labels", {}).values())
        ):
            raise TraceError("录制目录配置格式错误。", code="invalid_directory_config")
        return data

    def roots(self):
        roots = [self.default_root, *self.config().get("roots", [])]
        if os.environ.get("CODEX_ROLLOUT_TRACE_ROOT"):
            roots.append(os.environ["CODEX_ROLLOUT_TRACE_ROOT"])
        return list(dict.fromkeys(Path(p).expanduser().resolve() for p in roots))

    def register(self, path, label=None):
        root = Path(path).expanduser().resolve()
        if not root.is_dir():
            raise TraceError("请选择存在的录制目录。", code="recording_directory_missing")
        with self.lock:
            config = self.config()
            roots = config.setdefault("roots", [])
            if str(root) not in roots:
                roots.append(str(root))
            if label and (root / "manifest.json").is_file():
                meta = self.manifest(root)
                config.setdefault("labels", {})[meta["id"]] = str(label)[:120]
            self.config_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temp = self.config_file.with_suffix(f".{os.getpid()}.tmp")
            temp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.chmod(0o600)
            temp.replace(self.config_file)
            self.last_scan = None
        return {"registered": True, "path": str(root)}

    def manifest(self, path, labels=None):
        data = read_json(safe_file(path, "manifest.json"), 1024 * 1024)
        if not isinstance(data, dict):
            raise TraceError("录制清单必须是 JSON 对象。", code="invalid_recording_manifest")
        version = data.get("schema_version")
        identities = {
            target: value
            for source, target in (("trace_id", "traceId"), ("root_thread_id", "threadId"))
            if isinstance(value := data.get(source), str) and ID_RE.fullmatch(value)
        }
        try:
            trace_id = identifier(data.get("trace_id"))
            thread_id = identifier(data.get("root_thread_id"))
            if type(version) is not int or version not in SUPPORTED_SCHEMAS:
                raise TraceFormatError(trace_id, thread_id, version)
            if data.get("raw_event_log") != "trace.jsonl":
                raise TraceError(
                    "该录制的事件文件布局尚不受支持。", code="unsupported_recording_layout"
                )
            started_at = data.get("started_at_unix_ms")
            if started_at is not None and (type(started_at) is not int or started_at < 0):
                raise TraceError("录制开始时间无效。", code="invalid_recording_manifest")
        except TraceError as exc:
            exc.info = {
                **identities,
                "schemaVersion": version if type(version) is int else None,
                "message": str(exc),
                "errorCode": exc.code,
                "errorParams": exc.params,
            }
            raise
        return {
            "id": trace_id,
            "threadId": thread_id,
            "startedAt": started_at,
            "schemaVersion": version,
            "label": (self.config().get("labels", {}) if labels is None else labels).get(
                trace_id, f"任务 {thread_id[:8]}"
            ),
            "_path": path,
        }

    def candidates(self):
        count = 0
        for root in self.roots():
            if not root.is_dir():
                continue
            if (root / "manifest.json").is_file():
                yield root
                continue
            with os.scandir(root) as entries:
                for entry in entries:
                    count += 1
                    if count > 10000:
                        raise TraceError(
                            "录制目录过大，请配置更具体的目录。",
                            code="recording_directory_too_large",
                            params={"limit": 10000},
                        )
                    if entry.is_dir(follow_symlinks=False):
                        yield Path(entry.path)

    def list(self, force=False):
        with self.lock:
            if force or self.last_scan is None or time.monotonic() - self.last_scan > 5:
                found = {}
                issues = []
                labels = self.config().get("labels", {})
                for path in self.candidates():
                    try:
                        item = self.manifest(path, labels)
                        found[item["id"]] = item
                    except TraceError as exc:
                        issues.append(
                            {
                                "name": path.name,
                                "message": str(exc),
                                "errorCode": exc.code,
                                "errorParams": exc.params,
                                **exc.info,
                            }
                        )
                    except OSError:
                        continue
                self.cache = found
                self.issues = issues
                self.last_scan = time.monotonic()
            return sorted(self.cache.values(), key=lambda x: x["startedAt"] or 0, reverse=True)

    def find(self, trace_id=None, thread_id=None):
        if trace_id:
            identifier(trace_id)
        if thread_id:
            identifier(thread_id)
        with self.lock:
            if trace_id and thread_id:
                item = self.find(trace_id=trace_id)
                if item and item["threadId"] != thread_id:
                    raise TraceError("录制与聊天标识不一致。", code="recording_thread_mismatch")
                return item
            if thread_id:
                # A resumed chat can create several bundles with the same root.
                # Pick the newest exact-root recording, never an unrelated task.
                return next(
                    (item for item in self.list(force=True) if item["threadId"] == thread_id), None
                )
            if trace_id and trace_id in self.cache:
                return self.cache[trace_id]
            # Explicit trace IDs resolve by bundle directory name first.
            roots = set(self.roots())
            for path in self.candidates():
                if not ((trace_id and trace_id in path.name) or path in roots):
                    continue
                try:
                    item = self.manifest(path)
                    if trace_id and item["id"] == trace_id:
                        self.cache[item["id"]] = item
                        return item
                except (OSError, TraceError):
                    continue
            if trace_id:
                for item in self.list(force=True):
                    if item["id"] == trace_id:
                        return item
        return None
