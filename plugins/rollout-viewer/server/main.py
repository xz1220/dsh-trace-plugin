#!/usr/bin/env python3
"""Local MCP Apps server and authenticated loopback preview for Rollout Viewer."""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from store import Store, TraceError, identifier

PLUGIN = Path(__file__).resolve().parents[1]
VERSION = '0.2.8'
URI = 'ui://rollout-viewer/viewer.html'
STORE = Store()


def definition(name, title, properties=None, required=None, app=False, ui=False, entry=False, write=False):
    meta = {}
    if app:
        meta.update({'ui': {'visibility': ['app']}, 'openai/visibility': 'private'})
    if ui:
        meta.setdefault('ui', {})['resourceUri'] = URI
        meta['openai/outputTemplate'] = URI
    if entry:
        meta['openai/ui'] = {'entrypoints': [{'type': 'thread'}]}
    return {'name': name, 'title': title, 'description': title,
            'inputSchema': {'type': 'object', 'properties': properties or {},
                            'required': required or [], 'additionalProperties': False},
            'annotations': {'readOnlyHint': not write, 'destructiveHint': False,
                            'idempotentHint': not write, 'openWorldHint': False}, '_meta': meta}


STRING = {'type': 'string'}
TRACE = {'traceId': STRING}
ROW = {**TRACE, 'rowId': STRING}
CELL = {**ROW, 'cellKey': STRING}
TOOLS = [
    definition('list_rollout_traces', 'List official rollout recordings', {'refresh': {'type': 'boolean'}}),
    definition('show_rollout_trace', 'Show an official rollout trace', {**TRACE, 'threadId': STRING, 'callId': STRING}, ui=True),
    definition('open_rollout_viewer', 'Rollout Viewer', app=True, ui=True, entry=True),
    definition('get_rollout_overview', 'Read paged execution records', {**TRACE, 'beforeSeq': {'type': 'integer'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 500}}, ['traceId'], app=True),
    definition('get_rollout_delta', 'Read new execution events', {**TRACE, 'revision': STRING}, ['traceId', 'revision'], app=True),
    definition('get_rollout_detail', 'Inspect the selected request or tool', ROW, ['traceId', 'rowId'], app=True),
    definition('get_rollout_record', 'Locate one execution record', {**ROW,'callId':STRING}, ['traceId'], app=True),
    definition('get_rollout_projection', 'Read DSH trajectory records', {**TRACE, 'rowIds':{'type':'array','items':STRING,'maxItems':500}, 'beforeSeq': {'type':'integer'}, 'afterSeq': {'type':'integer'}, 'limit': {'type':'integer','minimum':1,'maximum':500}}, ['traceId'], app=True),
    definition('get_rollout_cell_detail', 'Inspect a DSH trajectory record', CELL, ['traceId','rowId','cellKey'], app=True),
    definition('read_rollout_cell_text', 'Read DSH record content in chunks', {**CELL, 'field':STRING, 'offset':{'type':'integer','minimum':0},'version':{'type':'integer','minimum':0}}, ['traceId','rowId','cellKey','field'], app=True),
    definition('get_rollout_request_info', 'Read complete request statistics', ROW, ['traceId','rowId'], app=True),
    definition('search_rollout_cells', 'Search loaded trajectory bodies', {**TRACE,'query':STRING,'rowIds':{'type':'array','items':STRING,'maxItems':1000},'locale':{'type':'string','enum':['zh','en','ja','es','fr','de','ru','pt']}}, ['traceId','query','rowIds'], app=True),
    definition('read_rollout_text', 'Read complete recorded content in chunks', {**ROW, 'section': {'type': 'string', 'enum': ['message','message_json','full_context','raw_request','response','tools','code','arguments','result','raw_result','runtime']}, 'itemIndex': {'type': 'integer'}, 'offset': {'type': 'integer', 'minimum': 0}}, ['traceId','rowId','section'], app=True),
    definition('add_rollout_directory', 'Add a local recording directory', {'path': STRING, 'label': STRING}, ['path'], app=True, write=True),
]


def call(name, args, metadata=None):
    spec = next((x for x in TOOLS if x['name'] == name), None)
    if not spec or not isinstance(args, dict):
        raise TraceError('未知工具或无效参数。')
    schema = spec['inputSchema']
    if set(args) - set(schema['properties']) or any(k not in args for k in schema['required']):
        raise TraceError('工具参数不完整或包含未知字段。')
    for key, value in args.items():
        field = schema['properties'][key]
        expected = field['type']
        if expected == 'string' and (not isinstance(value, str) or len(value) > 4096):
            raise TraceError('字符串参数无效。')
        if expected == 'integer' and (type(value) is not int or value < field.get('minimum', 0) or value > field.get('maximum', 10**9)):
            raise TraceError('数值参数超出范围。')
        if expected == 'boolean' and type(value) is not bool:
            raise TraceError('布尔参数无效。')
        if expected == 'array' and (not isinstance(value, list) or len(value) > field.get('maxItems',1000)
                                    or any(not isinstance(item,str) or len(item)>4096 for item in value)):
            raise TraceError('列表参数无效。')
        if 'enum' in field and value not in field['enum']:
            raise TraceError('参数不在支持的选项中。')
    if name == 'list_rollout_traces':
        return STORE.list(args.get('refresh', False))
    if name == 'open_rollout_viewer':
        meta = metadata if isinstance(metadata, dict) else {}
        first, second = meta.get('thread_id'), meta.get('threadId')
        thread_id = first or second
        if first and second and first != second:
            thread_id = None
        return STORE.open(thread_id=thread_id)
    if name == 'show_rollout_trace':
        result = STORE.open(args.get('traceId'), args.get('threadId'))
        # Public model calls only launch the UI; detailed metadata stays in app-only calls.
        if result.get('view')!='trace':
            return result
        launch={'view':'open','trace':result['trace']}
        if args.get('callId') is not None:
            launch['focusCallId']=identifier(args['callId'])
        return launch
    if name == 'get_rollout_overview':
        return STORE.index(args['traceId']).overview(args.get('limit', 200), args.get('beforeSeq'))
    if name == 'get_rollout_delta':
        return STORE.index(args['traceId']).delta(args['revision'])
    if name == 'get_rollout_detail':
        return STORE.details(args['traceId'], args['rowId'])
    if name == 'get_rollout_record':
        if ('rowId' in args)==('callId' in args):
            raise TraceError('请选择记录标识或调用标识之一。')
        if 'callId' in args:
            return {'row':STORE.locate_call(args['traceId'],args['callId'])}
        index = STORE.index(args['traceId'])
        return {'row': index.public_row(index.get_row(args['rowId']))}
    if name == 'get_rollout_projection':
        return STORE.projection(args['traceId']).page(args.get('limit',200),args.get('beforeSeq'),args.get('afterSeq'),args.get('rowIds'))
    if name == 'get_rollout_cell_detail':
        return STORE.cell_detail(args['traceId'],args['rowId'],args['cellKey'])
    if name == 'read_rollout_cell_text':
        return STORE.cell_text(args['traceId'],args['rowId'],args['cellKey'],args['field'],args.get('offset',0),args.get('version'))
    if name == 'get_rollout_request_info':
        projector = STORE.projection(args['traceId'])
        with projector.index.lock:
            row = projector.index.get_row(args['rowId'])
            if row.get('type') not in ('request','compaction'):
                raise TraceError('这条记录不是模型请求。')
            return {'request':projector.request_info(row,cumulative=True)}
    if name == 'search_rollout_cells':
        projector = STORE.projection(args['traceId'])
        with projector.index.lock:
            return {'matches':projector.search(args['query'],args['rowIds'],args.get('locale','zh'))}
    if name == 'read_rollout_text':
        return STORE.text(args['traceId'], args['rowId'], args['section'], args.get('itemIndex'), args.get('offset', 0))
    if name == 'add_rollout_directory':
        return STORE.catalog.register(args['path'], args.get('label'))
    raise TraceError('未知工具。')


def envelope(name, data):
    result = {'structuredContent': data, 'content': [{'type': 'text', 'text':
              'Rollout Viewer is ready.' if data.get('view') else 'Local recording data loaded.'}]}
    if name in ('show_rollout_trace', 'open_rollout_viewer'):
        result['_meta'] = {'ui': {'resourceUri': URI}}
    return result


def handle(method, params):
    if method == 'initialize':
        requested = params.get('protocolVersion')
        return {'protocolVersion': requested if requested in ('2025-06-18','2025-11-25') else '2025-06-18',
                'capabilities': {'tools': {}, 'resources': {}},
                'serverInfo': {'name': 'rollout-viewer', 'version': VERSION}}
    if method == 'ping':
        return {}
    if method == 'tools/list':
        return {'tools': TOOLS}
    if method == 'tools/call':
        try:
            return envelope(params.get('name'), call(params.get('name'), params.get('arguments', {}), params.get('_meta')))
        except (TraceError, OSError) as exc:
            text = str(exc) if isinstance(exc, TraceError) else '无法读取本地录制文件。'
            return {'isError': True, 'content': [{'type': 'text', 'text': text}], 'structuredContent': {'error': text}}
    if method == 'resources/list':
        return {'resources': [{'uri': URI, 'name': 'Rollout Viewer', 'mimeType': 'text/html;profile=mcp-app'}]}
    if method in ('resources/templates/list','prompts/list'):
        return {'resourceTemplates' if method.startswith('resources') else 'prompts': []}
    if method == 'resources/read' and params.get('uri') == URI:
        return {'contents': [{'uri': URI, 'mimeType': 'text/html;profile=mcp-app',
                             'text': (PLUGIN/'assets/viewer.html').read_text(),
                             '_meta': {'ui': {'prefersBorder': True}}}]}
    raise TraceError('不支持的 MCP 方法。')


def stdio():
    output_lock = threading.Lock()
    def process(request):
        identifier = request.get('id')
        try:
            params = request.get('params') or {}
            if not isinstance(params, dict):
                raise TraceError('Invalid params')
            response = {'jsonrpc': '2.0', 'id': identifier, 'result': handle(request.get('method'), params)}
        except Exception as exc:
            response = {'jsonrpc': '2.0', 'id': identifier, 'error': {'code': -32603, 'message': str(exc) if isinstance(exc, TraceError) else 'Local viewer error'}}
        with output_lock:
            sys.stdout.write(json.dumps(response, ensure_ascii=False, allow_nan=False)+'\n')
            sys.stdout.flush()
    with ThreadPoolExecutor(max_workers=4) as pool:
        for line in sys.stdin.buffer:
            if len(line) > 2 * 1024 * 1024:
                continue
            try:
                request = json.loads(line)
            except ValueError:
                continue
            if isinstance(request, dict) and 'id' in request:
                pool.submit(process, request)


def preview_server(port, trace_id=None):
    token = secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def send(self, status, body, mime='application/json', cookie=None):
            data = body.encode() if isinstance(body, str) else body
            self.send_response(status)
            self.send_header('Content-Type', mime+'; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            if cookie:
                self.send_header('Set-Cookie', cookie)
            self.end_headers()
            self.wfile.write(data)
        def authorized(self):
            cookie = self.headers.get('Cookie', '')
            return any(hmac.compare_digest(p.strip(), 'rollout_preview='+token) for p in cookie.split(';'))
        def do_GET(self):
            path = urlparse(self.path).path
            if path == '/open/'+token:
                self.send_response(302)
                self.send_header('Set-Cookie', f'rollout_preview={token}; HttpOnly; SameSite=Strict; Path=/')
                self.send_header('Location', '/')
                self.end_headers()
            elif path == '/' and self.authorized():
                html = (PLUGIN/'assets/viewer.html').read_text()
                bootstrap = json.dumps({'preview': True, 'traceId': trace_id}).replace('<','\\u003c')
                html = html.replace('<!--BOOTSTRAP-->', '<script>window.__ROLLOUT_PREVIEW__='+bootstrap+';</script>')
                self.send(200, html, 'text/html')
            elif path == '/native-frame' and self.authorized():
                self.send(200, (PLUGIN/'assets/viewer.html').read_text(), 'text/html')
            elif path == '/harness' and self.authorized():
                selected = json.dumps(trace_id).replace('<','\\u003c')
                html = '''<!doctype html><html><head><meta charset="utf-8"><title>MCP Apps handshake validation</title></head><body style="margin:0"><iframe title="Rollout Viewer native bridge" src="/native-frame" style="border:0;width:100vw;height:100vh"></iframe><script>
const frame=document.querySelector('iframe');window.bridgeCalls=[];
async function invoke(name,args){const response=await fetch('/api',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,arguments:args})});return response.json();}
addEventListener('message',async event=>{if(event.source!==frame.contentWindow||event.data?.jsonrpc!=='2.0')return;const m=event.data;const send=value=>frame.contentWindow.postMessage({jsonrpc:'2.0',...value},location.origin);
if(m.method==='ui/initialize'){window.bridgeCalls.push(m.method);send({id:m.id,result:{protocolVersion:'2026-01-26',hostInfo:{name:'local-validation',version:'1'},hostCapabilities:{},hostContext:{theme:'light',locale:'zh-CN',displayMode:'fullscreen'}}});}
else if(m.method==='ui/notifications/initialized'){window.bridgeCalls.push(m.method);const result=await invoke('show_rollout_trace',{traceId:TRACE_ID});send({method:'ui/notifications/tool-result',params:result});}
else if(m.method==='tools/call'){window.bridgeCalls.push(m.params.name);const result=await invoke(m.params.name,m.params.arguments||{});send({id:m.id,result});}});
</script></body></html>'''.replace('TRACE_ID', selected)
                self.send(200, html, 'text/html')
            else:
                self.send(403, '{"error":"Preview access required"}')
        def do_POST(self):
            origin = self.headers.get('Origin')
            allowed = f'http://127.0.0.1:{self.server.server_port}'
            if self.path != '/api' or not self.authorized() or origin not in (None, allowed):
                self.send(403, '{"error":"Forbidden"}')
                return
            length = int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 2*1024*1024:
                self.send(413, '{"error":"Request too large"}')
                return
            try:
                request = json.loads(self.rfile.read(length))
                result = envelope(request['name'], call(request['name'], request.get('arguments', {})))
                self.send(200, json.dumps(result, ensure_ascii=False))
            except (ValueError, OSError, KeyError) as exc:
                message = str(exc) if isinstance(exc, TraceError) else '请求失败'
                self.send(400, json.dumps({'error': message}, ensure_ascii=False))
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(json.dumps({'url': f'http://127.0.0.1:{server.server_port}/open/{token}', 'port': server.server_port}), flush=True)
    server.serve_forever()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--trace-id')
    parser.add_argument('--register')
    parser.add_argument('--label')
    parser.add_argument('--config-file')
    args = parser.parse_args()
    if args.config_file:
        STORE = Store(args.config_file)
    if args.register:
        print(json.dumps(STORE.catalog.register(args.register, args.label)))
    elif args.preview:
        preview_server(args.port, args.trace_id)
    else:
        stdio()
