"""Benchmark synthetic recordings by default; local real recordings are opt-in."""

import argparse
import json
import os
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/codex-dsh-trace/server"))
sys.path.insert(0, str(ROOT / "tests"))
from fixtures import Fixture
from store import Store


def timed(fn):
    start = time.perf_counter()
    value = fn()
    return value, (time.perf_counter() - start) * 1000


def sample(index):
    data, cold = timed(index.overview)
    before = index.metrics.copy()
    warm = [timed(index.overview)[1] for _ in range(30)]
    delta = [timed(lambda: index.delta(data["revision"]))[1] for _ in range(30)]
    return {
        "rows": data["totalRows"],
        "initialIndexMs": round(cold, 3),
        "warmPageP50Ms": round(statistics.median(warm), 3),
        "warmPageP95Ms": round(sorted(warm)[28], 3),
        "unchangedPollP50Ms": round(statistics.median(delta), 3),
        "initialPayloadReads": before["payloadReads"],
        "warmExtraLogBytes": index.metrics["logBytesRead"] - before["logBytesRead"],
    }


def projection_sample(store, index):
    before = index.metrics["payloadReads"]
    page, elapsed = timed(lambda: store.projection(index.meta["id"]).page())
    return {
        "initialProjectionMs": round(elapsed, 3),
        "projectedCells": len(page["cells"]),
        "projectionPayloadReads": index.metrics["payloadReads"] - before,
        "projectionResponseBytes": len(json.dumps(page, ensure_ascii=False).encode()),
    }


def synthetic_sample(rows):
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        fixture = Fixture(root / "bundle")
        ref = fixture.payload({"input": []}, "inference_request")
        with (fixture.root / "trace.jsonl").open("w", encoding="utf-8") as stream:
            for number in range(rows):
                events = (
                    fixture.event(
                        "inference_started",
                        inference_call_id=str(number),
                        model="test",
                        request_payload=ref,
                    ),
                    fixture.event(
                        "inference_completed",
                        inference_call_id=str(number),
                        response_id=f"r{number}",
                        response_payload=None,
                    ),
                )
                for event in events:
                    stream.write(json.dumps(event) + "\n")
        store = Store(root / "config.json")
        store.catalog.default_root = root / "default"
        # Resolve directly from synthetic metadata without scanning configured local roots.
        metadata = store.catalog.manifest(fixture.root)
        store.catalog.cache = {metadata["id"]: metadata}
        index = store.index(metadata["id"])
        result = sample(index)
        result.update(projection_sample(store, index))
        return result


def real_sample(trace_id):
    store = Store()
    index = store.index(trace_id)
    result = sample(index)
    row = next(
        (row for row in reversed(list(index.rows.values())) if row.get("type") == "request"), None
    )
    if row is not None:
        detail, elapsed = timed(lambda: store.details(trace_id, row["id"]))
        result.update(
            fullContextMetadataMs=round(elapsed, 3),
            messages=len(detail["messages"]),
            contextComplete=detail["context"]["complete"],
        )
    result.update(projection_sample(store, index))
    return result


def large_body_sample():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        fixture = Fixture(root / "bundle")
        request = fixture.payload({"input": []}, "inference_request")
        fixture.append("inference_started", inference_call_id="large", request_payload=request)
        content = "X" * (3 * 1024 * 1024)
        response = fixture.payload(
            {
                "output_items": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": content}],
                    }
                ]
            },
            "inference_response",
        )
        fixture.append("inference_completed", inference_call_id="large", response_payload=response)
        store = Store(root / "config.json")
        metadata = store.catalog.manifest(fixture.root)
        store.catalog.cache = {metadata["id"]: metadata}
        projector = store.projection(metadata["id"])
        with patch.object(projector, "build_detail", wraps=projector.build_detail) as builds:
            start = time.perf_counter()
            selected = store.cell_detail(metadata["id"], "request:large", "assistant")
            offset, pages, characters = 0, 0, 0
            while offset is not None:
                page = store.cell_text(
                    metadata["id"],
                    "request:large",
                    "assistant",
                    "outputDetail",
                    offset=offset,
                    snapshot=selected["snapshot"],
                )
                pages += 1
                characters += len(page["text"])
                offset = page["nextOffset"]
            return {
                "characters": characters,
                "pages": pages,
                "detailBuilds": builds.call_count,
                "elapsedMs": round((time.perf_counter() - start) * 1000, 3),
            }


def thread_poll_sample():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        # The full aggregate path scans roots; isolate both fallback locations.
        with patch.dict(
            os.environ,
            {
                "CODEX_HOME": str(root / "home"),
                "CODEX_ROLLOUT_TRACE_ROOT": str(root / "recordings"),
            },
        ):
            for number in range(10):
                fixture = Fixture(root / "recordings" / str(number))
                path = fixture.root / "manifest.json"
                manifest = json.loads(path.read_text())
                manifest["trace_id"] = f"trace-{number}"
                path.write_text(json.dumps(manifest))
                if number == 0:
                    fixture.conversation()
            store = Store(root / "config.json")
            trace = store.binding("thread-root")["trace"]["id"]
            index = store.index(trace)
            revision = index.overview()["revision"]
            with patch.object(store.catalog, "manifest", wraps=store.catalog.manifest) as reads:
                elapsed = [timed(lambda: index.delta(revision))[1] for _ in range(30)]
                return {
                    "recordings": 10,
                    "polls": len(elapsed),
                    "manifestReads": reads.call_count,
                    "pollP50Ms": round(statistics.median(elapsed), 3),
                }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--trace-id", help="Optionally include one local real recording (never needed in CI)"
    )
    parser.add_argument(
        "--rows", type=int, default=10000, help="Number of synthetic request rows (default: 10000)"
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if not 1 <= args.rows <= 100000:
        parser.error("--rows must be between 1 and 100000")
    synthetic = synthetic_sample(args.rows)
    report = {
        "pluginVersion": json.loads((ROOT / "package.json").read_text())["version"],
        "python": platform.python_version(),
        "platform": platform.machine(),
        "syntheticRows": args.rows,
        "synthetic": synthetic,
        "largeBody": large_body_sample(),
        "threadPolling": thread_poll_sample(),
        "scope": "Local backend timings; OS filesystem cache may already be warm. UI and MCP bridge latency are measured separately.",
    }
    if args.rows == 10000:
        report["synthetic10000Rows"] = synthetic
    if args.trace_id:
        report["realRecording"] = real_sample(args.trace_id)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
