"""Bounded immutable text snapshots shared by both paging APIs."""

import secrets
import threading
from collections import OrderedDict

from store import CHUNK, TraceError


class Snapshots:
    def __init__(self, max_bytes=128 * 1024 * 1024, max_entries=8):
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        self.entries = OrderedDict()
        self.bytes = 0
        self.lock = threading.RLock()

    def create(self, identity, fields):
        token = secrets.token_hex(16)
        size = sum(len(text) * 4 for text in fields.values())
        with self.lock:
            self.entries[token] = (identity, fields, size)
            self.bytes += size
            # An active selection may exceed the budget; retain its one snapshot.
            while len(self.entries) > 1 and (
                self.bytes > self.max_bytes or len(self.entries) > self.max_entries
            ):
                _, (_, _, removed) = self.entries.popitem(last=False)
                self.bytes -= removed
        return token

    def page(self, token, identity, field, offset):
        with self.lock:
            entry = self.entries.get(token)
            if entry is None or entry[0] != identity or field not in entry[1]:
                raise TraceError("记录已更新，请重新读取内容。", code="content_updated")
            self.entries.move_to_end(token)
            text = entry[1][field]
            if type(offset) is not int or not 0 <= offset <= len(text):
                raise TraceError("无效的文本分页位置。", code="invalid_text_offset")
            end = min(len(text), offset + CHUNK)
            return {
                "text": text[offset:end],
                "available": True,
                "totalChars": len(text),
                "offset": offset,
                "nextOffset": end if end < len(text) else None,
                "snapshot": token,
            }
