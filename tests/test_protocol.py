"""Exercise the public MCP and loopback HTTP boundaries with synthetic data."""

import http.client
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.cookies import SimpleCookie
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/codex-dsh-trace/server"))

import main
from fixtures import Fixture
from store import Store


class SyntheticRecordingCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        isolated = patch.dict(os.environ, {"CODEX_ROLLOUT_TRACE_ROOT": str(self.root / "unused")})
        isolated.start()
        self.addCleanup(isolated.stop)
        self.store = Store(self.root / "config.json")
        self.store.catalog.default_root = self.root / "default"
        self.fixture = Fixture(self.root / "recording")
        self.fixture.conversation()
        self.store.catalog.register(str(self.fixture.root))


class ProtocolTests(SyntheticRecordingCase):
    def rpc(self, requests):
        output = io.StringIO()
        main.stdio(store=self.store, input_stream=io.BytesIO(requests), output_stream=output)
        return [json.loads(line) for line in output.getvalue().splitlines()]

    def test_initialize_negotiates_supported_versions(self):
        for version in ("2025-06-18", "2025-11-25"):
            result = main.handle("initialize", {"protocolVersion": version}, store=self.store)
            self.assertEqual(result["protocolVersion"], version)
            self.assertEqual(result["serverInfo"]["version"], main.VERSION)
            self.assertIn("resources", result["capabilities"])
        self.assertEqual(
            main.handle("initialize", {"protocolVersion": "future"})["protocolVersion"],
            "2025-06-18",
        )

    def test_resources_include_versioned_and_legacy_resource(self):
        listing = main.handle("resources/list", {})["resources"]
        self.assertEqual(listing[0]["uri"], main.URI)
        for uri in (main.URI, main.LEGACY_URI):
            item = main.handle("resources/read", {"uri": uri})["contents"][0]
            self.assertEqual(item["uri"], uri)
            self.assertEqual(item["mimeType"], "text/html;profile=mcp-app")
            self.assertIn("<!doctype html>", item["text"].lower())

    def test_tools_preserve_privacy_hints_and_launch_envelope(self):
        tools = {tool["name"]: tool for tool in main.handle("tools/list", {})["tools"]}
        self.assertTrue(tools["show_rollout_trace"]["annotations"]["readOnlyHint"])
        self.assertFalse(tools["add_rollout_directory"]["annotations"]["readOnlyHint"])
        self.assertEqual(tools["get_rollout_detail"]["_meta"]["ui"]["visibility"], ["app"])
        result = main.handle(
            "tools/call",
            {"name": "show_rollout_trace", "arguments": {"traceId": "trace-test"}},
            store=self.store,
        )
        self.assertEqual(set(result["structuredContent"]), {"view", "trace"})
        self.assertEqual(result["_meta"]["ui"]["resourceUri"], main.URI)
        self.assertNotIn("Controlled prompt", json.dumps(result))

    def test_tool_validation_returns_localizable_errors(self):
        invalid = [
            ("unknown", {}, "invalid_tool"),
            ("get_rollout_detail", {"traceId": "trace-test"}, "invalid_tool_arguments"),
            ("list_rollout_traces", {"unknown": True}, "invalid_tool_arguments"),
            ("list_rollout_traces", {"refresh": 1}, "invalid_tool_arguments"),
            (
                "get_rollout_overview",
                {"traceId": "trace-test", "limit": True},
                "invalid_tool_arguments",
            ),
            (
                "get_rollout_overview",
                {"traceId": "trace-test", "limit": 501},
                "invalid_tool_arguments",
            ),
            (
                "get_rollout_projection",
                {"traceId": "trace-test", "rowIds": [1]},
                "invalid_tool_arguments",
            ),
            (
                "read_rollout_text",
                {"traceId": "trace-test", "rowId": "request:first", "section": "secret"},
                "invalid_tool_arguments",
            ),
            (
                "add_rollout_directory",
                {"path": str(self.root / "missing")},
                "recording_directory_missing",
            ),
            ("get_rollout_record", {"traceId": "trace-test"}, "invalid_locator"),
        ]
        for name, arguments, code in invalid:
            with self.subTest(name=name, arguments=arguments):
                result = main.handle(
                    "tools/call", {"name": name, "arguments": arguments}, store=self.store
                )
                self.assertTrue(result["isError"])
                data = result["structuredContent"]
                self.assertEqual(data["errorCode"], code)
                self.assertEqual(result["content"][0]["text"], data["error"])
                self.assertIsInstance(data["errorParams"], dict)

    def test_io_errors_do_not_expose_local_paths(self):
        with patch.object(self.store, "list", side_effect=OSError("/private/secret")):
            result = main.handle("tools/call", {"name": "list_rollout_traces"}, store=self.store)
        self.assertEqual(result["structuredContent"]["errorCode"], "local_read_failed")
        self.assertNotIn("/private/secret", json.dumps(result))

    def test_stdio_recovers_after_bad_input_and_ignores_notifications(self):
        requests = [
            b"not json\n",
            b"[]\n",
            b'{"jsonrpc":"2.0","id":true,"method":"ping"}\n',
            b'{"id":99,"method":"ping"}\n',
            b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n',
            b'{"jsonrpc":"2.0","id":1,"method":"unknown"}\n',
            b'{"jsonrpc":"2.0","id":2,"method":"ping","params":[]}\n',
            b'{"jsonrpc":"2.0","id":3,"method":"resources/read","params":{"uri":"file:///secret"}}\n',
            b'{"jsonrpc":"2.0","id":4,"method":"ping"}\n',
            b'{"jsonrpc":"2.0","id":NaN,"method":"ping"}\n',
        ]
        responses = self.rpc(b"".join(requests))
        self.assertEqual(len(responses), 9)
        errors = [item["error"]["code"] for item in responses if "error" in item]
        self.assertEqual(
            sorted(errors), sorted([-32700, -32600, -32600, -32600, -32601, -32602, -32602, -32700])
        )
        by_id = {item["id"]: item for item in responses if item["id"] is not None}
        self.assertEqual(by_id[4]["result"], {})
        self.assertEqual(by_id[1]["error"]["code"], -32601)
        self.assertEqual(by_id[2]["error"]["code"], -32602)
        self.assertEqual(by_id[3]["error"]["code"], -32602)

    def test_stdio_bounds_oversized_lines_and_recovers(self):
        responses = self.rpc(
            b"x" * (2 * 1024 * 1024 + 10) + b"\n" + b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n'
        )
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0]["error"]["code"], -32600)
        self.assertEqual(responses[1]["result"], {})

    def test_stdio_hides_unexpected_exception_details(self):
        with patch.object(main, "handle", side_effect=RuntimeError("PRIVATE_CONTENT")):
            responses = self.rpc(b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n')
        self.assertEqual(responses[0]["error"]["code"], -32603)
        self.assertNotIn("PRIVATE_CONTENT", json.dumps(responses))

    def test_cli_stdio_starts_without_personal_recordings(self):
        request = (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "init",
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-11-25"},
                }
            )
            + "\n"
        )
        result = subprocess.run(
            [
                sys.executable,
                str(Path(main.__file__)),
                "--config-file",
                str(self.root / "empty.json"),
            ],
            input=request,
            text=True,
            capture_output=True,
            check=True,
            timeout=10,
        )
        response = json.loads(result.stdout)
        self.assertEqual(response["id"], "init")
        self.assertEqual(response["result"]["serverInfo"]["version"], main.VERSION)
        self.assertEqual(result.stderr, "")


class PreviewTests(SyntheticRecordingCase):
    def setUp(self):
        super().setUp()
        self.servers = []
        self.addCleanup(self.close_servers)

    def close_servers(self):
        for server, thread in self.servers:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def start_server(self):
        server = main.create_preview_server(0, store=self.store)
        thread = threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.01), daemon=True
        )
        thread.start()
        self.servers.append((server, thread))
        return server

    def request(self, server, method="GET", path="/", body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def authenticate(self, server):
        status, headers, _ = self.request(server, path=urlparse(server.open_url).path)
        self.assertEqual(status, 302)
        cookie = SimpleCookie(headers["Set-Cookie"])
        self.assertTrue(cookie[server.cookie_name]["httponly"])
        self.assertEqual(cookie[server.cookie_name]["samesite"], "Strict")
        return cookie.output(header="", sep=";").strip().split(";", 1)[0]

    def test_multiple_ports_keep_independent_authenticated_sessions(self):
        first, second = self.start_server(), self.start_server()
        self.assertNotEqual(first.cookie_name, second.cookie_name)
        cookies = self.authenticate(first) + "; " + self.authenticate(second)
        for server in (first, second):
            status, headers, body = self.request(server, headers={"Cookie": cookies})
            self.assertEqual(status, 200)
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertEqual(headers["Referrer-Policy"], "no-referrer")
            self.assertIn(b"<!doctype html>", body.lower())
            self.assertEqual(server.socket.getsockname()[0], "127.0.0.1")

    def test_preview_requires_its_own_cookie(self):
        first, second = self.start_server(), self.start_server()
        for cookie in ("", "unrelated=caf\u00e9", self.authenticate(second)):
            status, _, body = self.request(first, headers={"Cookie": cookie})
            self.assertEqual(status, 403)
            self.assertEqual(json.loads(body)["errorCode"], "preview_access_required")

    def test_cross_origin_post_is_rejected_even_with_valid_cookie(self):
        server = self.start_server()
        cookie = self.authenticate(server)
        body = json.dumps({"name": "list_rollout_traces"})
        for origin in (
            "https://example.invalid",
            "null",
            f"http://127.0.0.1:{server.server_port + 1}",
        ):
            status, _, response = self.request(
                server, "POST", "/api", body, {"Cookie": cookie, "Origin": origin}
            )
            self.assertEqual(status, 403)
            self.assertEqual(json.loads(response)["errorCode"], "forbidden")
        status, _, response = self.request(
            server,
            "POST",
            "/api",
            body,
            {"Cookie": cookie, "Origin": f"http://127.0.0.1:{server.server_port}"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(response)["structuredContent"]["traces"]), 1)

    def test_http_validation_recovers_and_returns_stable_error_codes(self):
        server = self.start_server()
        cookie = self.authenticate(server)
        headers = {"Cookie": cookie}
        for payload in ("[]", "{", '{"name":1}'):
            status, _, response = self.request(server, "POST", "/api", payload, headers)
            self.assertEqual(status, 400)
            self.assertEqual(json.loads(response)["errorCode"], "invalid_request")
        status, _, response = self.request(
            server, "POST", "/api", "{}", {**headers, "Content-Length": "invalid"}
        )
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(response)["errorCode"], "invalid_request")
        status, _, response = self.request(
            server, "POST", "/api", "", {**headers, "Content-Length": "2097153"}
        )
        self.assertEqual(status, 413)
        self.assertEqual(json.loads(response)["errorCode"], "request_too_large")
        payload = json.dumps(
            {"name": "add_rollout_directory", "arguments": {"path": str(self.root / "missing")}}
        )
        status, _, response = self.request(server, "POST", "/api", payload, headers)
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(response)["errorCode"], "recording_directory_missing")
        status, _, _ = self.request(server, headers=headers)
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
