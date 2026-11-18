"""Isolated adapter for an explicitly scoped, read-only reader reconciliation.

stdin contains the already-validated manifest/event snapshots. stdout is a private
in-memory JSON transport to reconcile.py, never the public/redacted report.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

MAX_TRANSPORT = 256 * 1024 * 1024
MAX_TEXT = 64 * 1024 * 1024


def pages(fetch):
    """Finish one immutable reader selection without mixing subsequent versions."""
    chunks, offset, snapshot, total = [], 0, None, None
    while True:
        page = fetch(offset, snapshot)
        if page.get("available") is False:
            raise ValueError("Reader selection is unavailable.")
        chunk = page.get("text")
        if not isinstance(chunk, str):
            raise ValueError("Reader selection has no text.")
        if offset and page.get("offset", offset) != offset:
            raise ValueError("Reader returned an unexpected text offset.")
        snapshot = page.get("snapshot", snapshot)
        page_total = page.get("totalChars")
        if total is not None and page_total != total:
            raise ValueError("Reader text length changed while paging.")
        total = page_total
        chunks.append(chunk)
        if sum(map(len, chunks)) > MAX_TEXT:
            raise ValueError("Reader text exceeds the reconciliation limit.")
        following = page.get("nextOffset")
        if following is None:
            value = "".join(chunks)
            if isinstance(total, int) and len(value) != total:
                raise ValueError("Reader did not return the complete selection.")
            return value
        if not isinstance(following, int) or following <= offset or not snapshot:
            raise ValueError("Reader pagination did not advance with a snapshot.")
        offset = following


def refs(value):
    if isinstance(value, dict):
        if {"raw_payload_id", "path", "kind"} <= value.keys():
            yield value["path"]
        for child in value.values():
            yield from refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from refs(child)


def run(spec, reader_dir):
    sys.path.insert(0, str(reader_dir))
    from bundle_index import BundleIndex
    from recording import PAYLOAD_RE, TraceError
    from store import Store

    output = {"items": [], "continuation": [], "errors": []}
    payload_reads = set()

    def error(stage, exc, row=None):
        output["errors"].append(
            {
                "stage": stage,
                "type": type(exc).__name__,
                "code": getattr(exc, "code", "adapter_error"),
                **({"rowId": row["id"], "turnId": row.get("turnId")} if row else {}),
            }
        )

    thread = spec["threadId"]
    selected_turns = set(spec["turnIds"])
    config = Path(spec["configDirectory"])
    if not config.is_absolute():
        raise ValueError("An absolute isolated config directory is required.")
    # No config is opened: catalog discovery is replaced by the explicit metas.
    store = Store(config / "unused-reader-config.json")
    metas = []
    store.catalog.default_root = config / "no-user-captures"
    store.catalog.roots = lambda: [meta["_path"] for meta in metas]
    store.catalog.list = lambda force=False: metas
    for capture in spec["captures"]:
        manifest, directory = capture["manifest"], Path(capture["path"])
        if manifest.get("root_thread_id") != thread:
            raise ValueError("Capture root thread does not match the explicit scope.")
        if not directory.is_absolute() or directory.is_symlink() or not directory.is_dir():
            raise ValueError("Capture directory is not an explicit ordinary directory.")
        events = capture["events"]
        for event in events:
            if event.get("thread_id") not in (None, thread):
                raise ValueError("Event thread does not match the explicit scope.")
        allowed = set(refs(events))
        if any(not isinstance(path, str) or not PAYLOAD_RE.fullmatch(path) for path in allowed):
            raise ValueError("Snapshot contains an unsafe payload reference.")
        meta = {
            "id": manifest["trace_id"],
            "threadId": thread,
            "schemaVersion": manifest["schema_version"],
            "startedAt": manifest.get("started_at_unix_ms"),
            "label": "Explicit reconciliation capture",
            "_path": directory,
        }

        class ScopedIndex(BundleIndex):
            def __init__(self, metadata, paths):
                super().__init__(metadata)
                self.allowed_paths = paths

            def refresh(self):
                # Never consume later-turn events from the live recording.
                return None

            def payload(self, ref):
                if ref:
                    relative = ref.get("path")
                    if relative not in self.allowed_paths:
                        raise TraceError(
                            "Payload is outside the explicit event snapshot.",
                            code="reconciliation_scope_violation",
                        )
                    payload_reads.add((self.meta["id"], relative))
                return super().payload(ref)

        index = ScopedIndex(meta, allowed)
        for event in events:
            index.apply(event)
            index.last_seq = event["seq"]
        metas.append(meta)
        store.catalog.cache[meta["id"]] = meta
        store.indexes[meta["id"]] = index

    identity = "thread@" + thread
    index = store.index(identity)
    index.refresh(force=True)
    rows = [row for row in index.rows.values() if row.get("turnId") in selected_turns]
    # Resolve all selected contexts before projecting. Learning a causal link can
    # change the aggregate epoch; take the actual page after it has stabilized.
    for row in rows:
        if row.get("type") == "request":
            try:
                index.context(row["id"])
            except Exception as exc:
                error("context", exc, row)
    projector = store.projection(identity)
    for _ in range(3):
        rows = [row for row in index.rows.values() if row.get("turnId") in selected_turns]
        page = projector.page(row_ids=[row["id"] for row in rows])
        if not page.get("resync"):
            break
    else:
        raise ValueError("Reader projection did not stabilize after resync.")
    cells = {(cell["rowId"], cell["cellKey"]): cell for cell in page["cells"]}

    def cell_text(row, field, detail):
        token = detail["snapshot"]
        return pages(
            lambda offset, _snapshot: store.cell_text(
                identity,
                row["id"],
                "tool" if row["type"] == "tool" else "assistant",
                field,
                offset=offset,
                snapshot=token,
            )
        )

    for row in rows:
        base = {
            "turnId": row.get("turnId"),
            "sourceTraceId": row.get("sourceTraceId"),
            "rowId": row["id"],
        }
        if row.get("type") == "request":
            inference = row.get("sourceRowId", row["id"]).removeprefix("request:")
            base["inferenceId"] = inference
            try:
                context = index.context(row["id"])
                raw = context["raw"]
                output["continuation"].append(
                    {
                        **base,
                        "previousResponseId": raw.get("previous_response_id"),
                        "contextComplete": context["complete"],
                        "missing": context["missing"],
                    }
                )
                for position, entry in enumerate(context["items"]):
                    value = entry["value"]
                    if entry["requestId"] != row["id"] or entry["origin"] != "input":
                        continue
                    if not isinstance(value, dict):
                        continue
                    is_user = value.get("role") == "user"
                    is_delegation = value.get("type") == "function_call_output" and value.get(
                        "name"
                    ) in {"create_thread", "send_message_to_thread"}
                    if not (is_user or is_delegation):
                        continue
                    rendered = pages(
                        lambda offset, snapshot: store.text(
                            identity,
                            row["id"],
                            "message",
                            item_index=position,
                            offset=offset,
                            snapshot=snapshot,
                        )
                    )
                    output["items"].append(
                        {
                            **base,
                            "kind": "input",
                            "id": value.get("id"),
                            "contextComplete": context["complete"],
                            "value": {
                                "type": value.get("type"),
                                "role": value.get("role"),
                                "name": value.get("name"),
                                "text": rendered,
                            },
                        }
                    )
            except Exception as exc:
                error("input", exc, row)
            try:
                if (row["id"], "assistant") in cells:
                    response = json.loads(
                        pages(
                            lambda offset, snapshot: store.text(
                                identity,
                                row["id"],
                                "response",
                                offset=offset,
                                snapshot=snapshot,
                            )
                        )
                    )
                    has_final = isinstance(response, dict) and any(
                        isinstance(item, dict)
                        and item.get("type") == "message"
                        and item.get("role") == "assistant"
                        and item.get("phase") == "final_answer"
                        for item in response.get("output_items", [])
                    )
                    if not has_final:
                        continue
                    detail = store.cell_detail(identity, row["id"], "assistant")
                    if "outputDetail" in detail["fields"]:
                        text = cell_text(row, "outputDetail", detail)
                        # Tool-only assistant rows have no final message body.
                        if text:
                            output["items"].append(
                                {**base, "kind": "final", "id": None, "value": {"text": text}}
                            )
            except Exception as exc:
                error("final", exc, row)
        elif row.get("type") == "tool":
            try:
                if (row["id"], "tool") not in cells:
                    raise ValueError("Tool row is missing from the projection page.")
                detail = store.cell_detail(identity, row["id"], "tool")
                # Only terminal requests have command/stdout/exit semantics.
                name = detail["cell"].get("qualifiedToolName") or row.get("name")
                if name not in {"exec_command", "functions.exec_command"}:
                    continue
                command = json.loads(cell_text(row, "inputDetail", detail)).get("cmd")
                result = cell_text(row, "outputDetail", detail)
                output["items"].append(
                    {
                        **base,
                        "kind": "tool",
                        "id": row.get("sourceRowId", row["id"]).split("tool:", 1)[-1],
                        "value": {
                            "command": command,
                            "output": result,
                            "exitCode": store.details(identity, row["id"]).get("exitCode"),
                        },
                    }
                )
            except Exception as exc:
                error("tool", exc, row)

    observed = {}
    for module in list(sys.modules.values()):
        filename = getattr(module, "__file__", None)
        if not filename:
            continue
        path = Path(filename).resolve()
        if path.parent == reader_dir and path.suffix == ".py":
            observed[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    version = reader_dir / "_version.py"
    output["provenance"] = {
        "kind": "isolated offline reader; not a live installed MCP process",
        "readerDir": str(reader_dir),
        "codeHashes": observed,
        "versionFileSha256": hashlib.sha256(version.read_bytes()).hexdigest()
        if version.is_file()
        else None,
        "selectedPayloadsRead": [
            {"traceId": source, "path": path} for source, path in sorted(payload_reads)
        ],
        "sourceConfigRead": False,
        "projectionResync": page.get("resync"),
    }
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reader-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(MAX_TRANSPORT + 1)
        if len(raw) > MAX_TRANSPORT:
            raise ValueError("Reconciliation transport exceeds the limit.")
        result = run(json.loads(raw), args.reader_dir.resolve())
    except Exception as exc:
        result = {
            "items": [],
            "continuation": [],
            "errors": [
                {
                    "stage": "reader",
                    "type": type(exc).__name__,
                    "code": getattr(exc, "code", "adapter_error"),
                }
            ],
        }
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
