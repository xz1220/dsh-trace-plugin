"""Read-only checks for installed files, MCP protocol, and an optional recording."""

import argparse
import hashlib
import json
import runpy
import select
import subprocess
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--plugin-dir", type=Path, required=True)
parser.add_argument(
    "--trace-id", help="Optionally inspect a recording, including empty or live ones."
)
parser.add_argument("--expect-text", action="append", default=[])
parser.add_argument("--out", type=Path)
args = parser.parse_args()
if args.expect_text and not args.trace_id:
    parser.error("--expect-text requires --trace-id")
root = args.plugin_dir.resolve()
# Reuse the distribution contract without running the packaging entrypoint.
files = runpy.run_path(str(SOURCE / "scripts/package-plugin.py"))["FILES"]
same = all(
    hashlib.sha256((SOURCE / "plugins/codex-dsh-trace" / relative).read_bytes()).digest()
    == hashlib.sha256((root / relative).read_bytes()).digest()
    for relative in files
)
assert same, "Installed files differ from the current distribution"
process = subprocess.Popen(
    [sys.executable, str(root / "server/main.py")],
    cwd=root,
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    text=True,
)
counter = 0


def rpc(method, params):
    global counter
    counter += 1
    process.stdin.write(
        json.dumps({"jsonrpc": "2.0", "id": counter, "method": method, "params": params}) + "\n"
    )
    process.stdin.flush()
    assert select.select([process.stdout], [], [], 10)[0], "MCP timed out"
    value = json.loads(process.stdout.readline())
    assert value.get("id") == counter and "error" not in value, "MCP request failed"
    return value["result"]


def call(name, arguments, metadata=None):
    params = {"name": name, "arguments": arguments}
    if metadata is not None:
        params["_meta"] = metadata
    result = rpc("tools/call", params)
    assert not result.get("isError"), "Tool failed"
    return result["structuredContent"]


def read_text(arguments):
    pieces = []
    offset = 0
    snapshot = None
    while offset is not None:
        page = call(
            "read_rollout_text",
            {**arguments, "offset": offset, **({"snapshot": snapshot} if snapshot else {})},
        )
        if page.get("available") is False:
            return ""
        snapshot = page["snapshot"]
        pieces.append(page["text"])
        offset = page["nextOffset"]
    return "".join(pieces)


try:
    version = rpc(
        "initialize",
        {
            "protocolVersion": "2025-11-25",
            "clientInfo": {"name": "install-check", "version": "1"},
            "capabilities": {},
        },
    )["serverInfo"]["version"]
    tools = {tool["name"]: tool for tool in rpc("tools/list", {})["tools"]}
    entry = tools["open_rollout_viewer"]
    assert entry["_meta"]["openai/ui"]["entrypoints"] == [{"type": "thread"}]
    private_names = {
        "get_rollout_projection",
        "get_rollout_cell_detail",
        "read_rollout_cell_text",
        "get_rollout_request_info",
        "search_rollout_cells",
        "get_rollout_binding",
    }
    assert private_names <= tools.keys()
    assert all(tools[name]["_meta"]["ui"]["visibility"] == ["app"] for name in private_names)
    for metadata in (
        {"threadId": "unrelated-install-check"},
        {"thread_id": "install-check-one", "threadId": "install-check-two"},
    ):
        assert call("open_rollout_viewer", {}, metadata)["view"] == "select"
    resource = rpc("resources/read", {"uri": "ui://rollout-viewer/viewer.html"})["contents"][0]
    assert resource["mimeType"] == "text/html;profile=mcp-app"
    current_uri = entry["_meta"]["ui"]["resourceUri"]
    current_resource = rpc("resources/read", {"uri": current_uri})["contents"][0]
    assert version in current_uri and current_resource["text"] == resource["text"]
    report = {
        "version": version,
        "tools": len(tools),
        "installedFilesMatchSource": same,
        "checkedInstalledFiles": files,
        "mcpInitialization": True,
        "nativeEntryMetadata": True,
        "detailedToolsAppOnly": True,
        "versionedResourceAndLegacyAlias": True,
        "appResourceBytes": len(resource["text"].encode()),
        "nativeDesktopMountVerified": False,
    }
    if args.trace_id:
        arguments = {"traceId": args.trace_id}
        launch = call("show_rollout_trace", arguments)
        assert launch["view"] == "open" and "rows" not in launch
        data = call("get_rollout_overview", arguments)
        thread_id = data["trace"]["threadId"]
        binding = call("get_rollout_binding", {"threadId": thread_id})
        assert binding["currentThreadId"] == thread_id
        assert binding["trace"]["threadId"] == thread_id
        projection = call("get_rollout_projection", arguments)
        assert all(cell["recordId"] for cell in projection["cells"])
        requests = [row for row in data["rows"] if row["type"] == "request"]
        content = ""
        if requests:
            content = read_text(
                {**arguments, "rowId": requests[-1]["id"], "section": "full_context"}
            )
        assert all(text in content for text in args.expect_text), (
            "Expected recorded content missing"
        )
        report["recording"] = {
            "requests": data["requestCount"],
            "tools": data["toolCount"],
            "dshCells": len(projection["cells"]),
            "expectedTextChecks": len(args.expect_text),
            "knownContextCharacters": len(content),
            "schemaVersion": data["trace"].get("schemaVersion"),
        }
    if args.out:
        args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
finally:
    process.stdin.close()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=5)
