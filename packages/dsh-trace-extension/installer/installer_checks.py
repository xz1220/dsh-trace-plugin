"""Bounded, read-only installation inspection and isolated backend probes."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import marshal
import os
import re
import selectors
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ENV_KEY = "CODEX_ROLLOUT_TRACE_ROOT"
FOREIGN_PYC_RE = re.compile(r"(.+)\.(cpython-3(?:9|1\d))(?:\.opt-([12]))?\.pyc\Z")


class CheckError(Exception):
    """An inspection cannot safely establish runtime health."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_path(path: Path) -> Path:
    for candidate in (path, *path.parents):
        if candidate.is_symlink():
            raise CheckError(f"Preserving symlinked installed path: {candidate}")
    return path


def read_bytes(path: Path) -> bytes | None:
    safe_path(path)
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > 128 * 1024 * 1024:
        raise CheckError(f"Preserving non-file or oversized installed path: {path}")
    return path.read_bytes()


def probe_backend(
    python: str,
    cache: Path,
    expected: dict[str, str],
    timeout: float = 5.0,
    limit: int = 128 * 1024,
) -> dict[str, Any]:
    """Probe only copied, hash-verified code with empty data and bounded I/O."""
    if not isinstance(expected, dict) or len(expected) > 1000:
        return {"status": "unknown", "reason": "Invalid installed file inventory."}
    for name in expected:
        if (
            not isinstance(name, str)
            or not name
            or "\\" in name
            or any(part in ("", ".", "..") for part in name.split("/"))
            or Path(name).is_absolute()
        ):
            return {"status": "unknown", "reason": "Invalid installed file path."}
    with tempfile.TemporaryDirectory(prefix="dsh-backend-probe-") as temporary:
        root = Path(temporary)
        plugin = root / "plugin"
        total = 0
        for name, checksum in expected.items():
            source = safe_path(cache / name)
            if not source.is_file() or source.stat().st_size > 128 * 1024 * 1024:
                return {
                    "status": "unknown",
                    "reason": "Installed files changed before the probe.",
                }
            data = source.read_bytes()
            total += len(data)
            if total > 128 * 1024 * 1024 or digest(data) != checksum:
                return {
                    "status": "unknown",
                    "reason": "Installed files changed before the probe.",
                }
            target = plugin / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        home, traces = root / "home", root / "recordings"
        home.mkdir(mode=0o700)
        traces.mkdir(mode=0o700)
        environment = {
            "HOME": str(home),
            "CODEX_HOME": str(home / ".codex"),
            ENV_KEY: str(traces),
            "PATH": os.defpath,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
        }
        requests = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "dsh-doctor", "version": "1"},
                },
            },
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        ]
        process = subprocess.Popen(
            [python, "-S", "-B", str(plugin / "server/main.py")],
            cwd=plugin,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        output: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
        deadline, problem = time.monotonic() + timeout, None
        selector = selectors.DefaultSelector()
        try:
            for stream_name in output:
                stream = getattr(process, stream_name)
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, stream_name)
            try:
                assert process.stdin is not None
                process.stdin.write(
                    ("\n".join(json.dumps(item) for item in requests) + "\n").encode()
                )
                process.stdin.close()
            except BrokenPipeError:
                pass
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    problem = "timeout"
                    break
                for key, _ in selector.select(min(remaining, 0.1)):
                    chunk = os.read(key.fd, min(65536, limit + 1))
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    output[key.data].extend(chunk)
                    if sum(map(len, output.values())) > limit:
                        problem = "output-limit"
                        break
                if problem:
                    break
            if not problem:
                try:
                    process.wait(timeout=max(0.01, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    problem = "timeout"
        finally:
            # Only this probe's newly-created session/process group is stopped.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=1)
            selector.close()
            for stream_name in ("stdin", "stdout", "stderr"):
                pipe = getattr(process, stream_name)
                if pipe is not None:
                    try:
                        pipe.close()
                    except BrokenPipeError:
                        pass
        if problem:
            return {
                "status": problem,
                "reason": "Backend probe stopped at its time/output budget.",
            }
        if process.returncode:
            return {
                "status": "failed",
                "reason": "Verified backend did not exit successfully in the isolated probe.",
            }
        try:
            replies = {
                item["id"]: item
                for item in (json.loads(line) for line in output["stdout"].decode().splitlines())
                if "id" in item
            }
            info = replies[1]["result"]["serverInfo"]
            tools = replies[2]["result"]["tools"]
            if (
                not isinstance(info.get("version"), str)
                or not isinstance(tools, list)
                or not any(tool.get("name") == "open_rollout_viewer" for tool in tools)
            ):
                raise ValueError("contract")
            return {
                "status": "verified",
                "version": info["version"],
                "tools": len(tools),
                "scope": "initialize/tools-list with empty private recording data; native UI not checked",
            }
        except (ValueError, KeyError, TypeError, AttributeError, UnicodeError):
            return {
                "status": "failed",
                "reason": "Backend probe did not return the expected MCP initialize/tools-list contract.",
            }


def inspect_cache(root: Path, version: str, expected: dict[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "verified",
        "verified": True,
        "path": str(root),
        "version": version,
        "missing": [],
        "modified": [],
        "extra": [],
        "generatedBytecode": [],
    }
    try:
        safe_path(root)
        total = 0
        for name, checksum in expected.items():
            path = root / name
            data = read_bytes(path)
            if data is None:
                result["missing"].append(name)
            else:
                total += len(data)
                if total > 128 * 1024 * 1024:
                    raise CheckError("Installed cache exceeds the inspection budget.")
                if digest(data) != checksum:
                    result["modified"].append(name)
        if root.exists():
            for index, path in enumerate(root.rglob("*")):
                if index >= 2000:
                    raise CheckError("Installed cache has too many entries to inspect safely.")
                if path.is_symlink():
                    raise CheckError(f"Installed cache contains a symlink: {path}")
                if path.is_file() and path.relative_to(root).as_posix() not in expected:
                    if known_bytecode(path, root, expected):
                        result["generatedBytecode"].append(path.relative_to(root).as_posix())
                    else:
                        result["extra"].append(path.relative_to(root).as_posix())
        result["verified"] = not (result["missing"] or result["modified"])
        if not result["verified"]:
            result["status"] = "modified" if result["modified"] else "missing-files"
    except (CheckError, OSError) as exc:
        result.update(status="unknown", verified=False, reason=str(exc))
    return result


def _matches_foreign_pyc_header(cached: bytes, source_data: bytes) -> bool:
    """Validate PEP 552 header fields for a stale CPython 3.9+ bytecode file without running it."""
    if len(cached) < 17 or cached[2:4] != b"\r\n":
        return False
    magic = int.from_bytes(cached[:2], "little")
    # CPython 3.9 starts at 3420; reject obviously unrelated binary headers.
    if not 3400 <= magic <= 4500:
        return False
    bitfield = int.from_bytes(cached[4:8], "little")
    if bitfield == 0:
        recorded_size = int.from_bytes(cached[12:16], "little")
        if recorded_size != (len(source_data) & 0xFFFFFFFF):
            return False
    elif bitfield in (1, 3):
        if cached[8:16] != importlib.util.source_hash(source_data):
            return False
    else:
        return False
    # CPython marshal code object type marker ('c' = 0x63, with optional FLAG_REF 0x80 = 0xE3).
    return cached[16:17] in (b"c", b"\xe3")


def known_bytecode(path: Path, root: Path, expected: dict[str, str]) -> bool:
    """Recognize only compiled copies of verified public source, never execute them."""
    if path.parent.name != "__pycache__" or path.stat().st_size > 16 * 1024 * 1024:
        return False
    cache_tag = sys.implementation.cache_tag
    current_match = (
        re.fullmatch(
            r"(.+)\." + re.escape(cache_tag) + r"(?:\.opt-([12]))?\.pyc",
            path.name,
        )
        if isinstance(cache_tag, str)
        else None
    )
    foreign_match = None if current_match else FOREIGN_PYC_RE.fullmatch(path.name)
    match = current_match or foreign_match
    if not match:
        return False
    source = path.parent.parent / (match[1] + ".py")
    if not source.is_file() or source.stat().st_size > 1024 * 1024:
        return False
    data = read_bytes(source)
    if data is None or digest(data) != expected.get(source.relative_to(root).as_posix()):
        return False
    cached = read_bytes(path)
    if cached is None or len(cached) < 16:
        return False
    if foreign_match is not None:
        if cached[:4] == importlib.util.MAGIC_NUMBER:
            return False
        return _matches_foreign_pyc_header(cached, data)
    if cached[:4] != importlib.util.MAGIC_NUMBER:
        return False
    try:
        compiled = compile(
            data, str(source), "exec", dont_inherit=True, optimize=int(match[2] or 0)
        )
        # CPython 3.14 may pass locals as borrowed references. Keep two owning
        # refs to match py_compile/importlib's root FLAG_REF and reference indexes.
        compiled_refs = (compiled, compiled)
        return cached[16:] == marshal.dumps(compiled_refs[0])
    except (SyntaxError, ValueError):
        return False
