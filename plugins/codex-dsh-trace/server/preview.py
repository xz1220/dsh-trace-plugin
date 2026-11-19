"""Authenticated loopback transport for the same local MCP tool dispatcher."""

from __future__ import annotations

import hmac
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from recording import TraceError


def preview_error(exc):
    if isinstance(exc, TraceError):
        return {"error": str(exc), "errorCode": exc.code, "errorParams": exc.params}
    return {"error": "无法读取本地录制文件。", "errorCode": "local_read_failed", "errorParams": {}}


class PreviewHTTPServer(ThreadingHTTPServer):
    cookie_name: str
    open_url: str


def create_preview_server(port, trace_id=None, *, store, dispatch, plugin) -> PreviewHTTPServer:
    """Create a loopback-only preview server without starting its event loop."""
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        server: PreviewHTTPServer

        def log_message(self, *args):
            pass

        def send(self, status, body, mime="application/json", cookie=None):
            data = body.encode() if isinstance(body, str) else body
            self.send_response(status)
            self.send_header("Content-Type", mime + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(data)

        def authorized(self):
            cookie = self.headers.get("Cookie", "")
            expected = (self.server.cookie_name + "=" + token).encode("ascii")
            return any(
                hmac.compare_digest(p.strip().encode("utf-8"), expected) for p in cookie.split(";")
            )

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/open/" + token:
                self.send_response(302)
                self.send_header(
                    "Set-Cookie",
                    f"{self.server.cookie_name}={token}; HttpOnly; SameSite=Strict; Path=/",
                )
                self.send_header("Location", "/")
                self.end_headers()
            elif path == "/" and self.authorized():
                html = (plugin / "assets/viewer.html").read_text(encoding="utf-8")
                bootstrap = json.dumps({"preview": True, "traceId": trace_id}).replace(
                    "<", "\\u003c"
                )
                html = html.replace(
                    "<!--BOOTSTRAP-->",
                    "<script>window.__ROLLOUT_PREVIEW__=" + bootstrap + ";</script>",
                )
                self.send(200, html, "text/html")
            elif path == "/native-frame" and self.authorized():
                self.send(
                    200, (plugin / "assets/viewer.html").read_text(encoding="utf-8"), "text/html"
                )
            elif path == "/harness" and self.authorized():
                meta = store.catalog.find(trace_id=trace_id) if trace_id else None
                config = json.dumps(
                    {
                        "traceId": trace_id,
                        "threadId": meta["threadId"] if meta else None,
                        "coldStart": urlparse(self.path).query == "cold=1",
                    }
                ).replace("<", "\\u003c")
                html = (plugin / "server/bridge-harness.html").read_text(encoding="utf-8")
                html = html.replace("__CONFIG__", config)
                self.send(200, html, "text/html")
            else:
                self.send(
                    403,
                    json.dumps(
                        {
                            "error": "Preview access required",
                            "errorCode": "preview_access_required",
                            "errorParams": {},
                        }
                    ),
                )

        def do_POST(self):
            origin = self.headers.get("Origin")
            allowed = f"http://127.0.0.1:{self.server.server_port}"
            if self.path != "/api" or not self.authorized() or origin not in (None, allowed):
                self.send(
                    403,
                    json.dumps({"error": "Forbidden", "errorCode": "forbidden", "errorParams": {}}),
                )
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.send(
                    400,
                    json.dumps(
                        {
                            "error": "Invalid Content-Length",
                            "errorCode": "invalid_request",
                            "errorParams": {},
                        }
                    ),
                )
                return
            if not 0 < length <= 2 * 1024 * 1024:
                self.send(
                    413,
                    json.dumps(
                        {
                            "error": "Request too large",
                            "errorCode": "request_too_large",
                            "errorParams": {},
                        }
                    ),
                )
                return
            try:
                request = json.loads(self.rfile.read(length))
                if not isinstance(request, dict) or not isinstance(request.get("name"), str):
                    raise TraceError("请求格式无效。", code="invalid_request")
                result = dispatch(request)
                self.send(200, json.dumps(result, ensure_ascii=False))
            except (ValueError, OSError, KeyError) as exc:
                data = (
                    preview_error(exc)
                    if isinstance(exc, (TraceError, OSError))
                    else {"error": "请求失败", "errorCode": "invalid_request", "errorParams": {}}
                )
                self.send(400, json.dumps(data, ensure_ascii=False))

    server = PreviewHTTPServer(("127.0.0.1", port), Handler)
    server.cookie_name = f"rollout_preview_{server.server_port}"
    server.open_url = f"http://127.0.0.1:{server.server_port}/open/{token}"
    return server
