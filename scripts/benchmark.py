"""Benchmark synthetic recordings by default; local real recordings are opt-in."""

import argparse
import json
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/codex-dsh-trace/server"))
sys.path.insert(0, str(ROOT / "tests"))
from store import Store
from test_store import Fixture


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
