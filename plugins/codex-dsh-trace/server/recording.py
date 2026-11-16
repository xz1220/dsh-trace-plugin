"""Recording format constants, stable errors, and validated local file reads."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

MAX_LOG = 256 * 1024 * 1024
MAX_PAYLOAD = 64 * 1024 * 1024
CHUNK = 48000
SUPPORTED_SCHEMAS = (1, 2)
ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")
PAYLOAD_RE = re.compile(r"^payloads/[A-Za-z0-9_.-]+\.json$")


class TraceError(ValueError):
    """A user-facing error with a stable code for client localization."""

    def __init__(
        self, message: str, *, code: str = "trace_error", params: Optional[dict[str, Any]] = None
    ):
        super().__init__(message)
        self.code = code
        self.params = dict(params or {})
        self.info: dict[str, Any] = {}


class TraceFormatError(TraceError):
    def __init__(self, trace_id, thread_id, version):
        label = str(version) if type(version) is int else "未知"
        super().__init__(
            f"录制格式版本 {label} 暂不支持，请更新 Codex Trace。",
            code="unsupported_schema",
            params={"version": version if type(version) is int else "?"},
        )
        self.info = {
            "traceId": trace_id,
            "threadId": thread_id,
            "schemaVersion": version if type(version) is int else None,
            "message": str(self),
            "errorCode": self.code,
            "errorParams": self.params,
        }


def identifier(value):
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise TraceError("无效的录制或记录标识。", code="invalid_identifier")
    return value


def safe_file(root, relative):
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise TraceError("录制文件路径超出允许范围。", code="unsafe_recording_path")
    path = root / rel
    part = root
    for name in rel.parts:
        part = part / name
        if part.is_symlink():
            raise TraceError("录制目录内不能包含符号链接。", code="recording_symlink")
    if not path.is_file() or path.stat().st_nlink != 1:
        raise TraceError(
            "录制文件不可用，或不是独立的普通文件。", code="recording_file_unavailable"
        )
    return path


def read_json(path, limit=MAX_PAYLOAD):
    if path.stat().st_size > limit:
        raise TraceError("该文件超过读取上限，未截断展示。", code="recording_file_too_large")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TraceError("录制文件不是有效的 UTF-8 JSON。", code="invalid_recording_json") from exc
