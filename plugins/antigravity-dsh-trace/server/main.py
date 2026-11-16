#!/usr/bin/env python3
"""MCP-compatible, read-only native Antigravity transcript provider for the sidecar."""
from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from native_store import NativeStore, TraceError

VERSION = '0.2.19'
STORE = NativeStore()
STRING = {'type': 'string'}
TRACE = {'traceId': STRING}
ROW = {**TRACE, 'rowId': STRING}
CELL = {**ROW, 'cellKey': STRING}


def definition(name, properties=None, required=None, public=False):
    return {'name': name, 'description': 'Read native Antigravity client-step logs. Raw model requests and complete request context are not recorded.',
            'inputSchema': {'type': 'object', 'properties': properties or {}, 'required': required or [], 'additionalProperties': False},
            'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True, 'openWorldHint': False},
            '_meta': {} if public else {'ui': {'visibility': ['app']}, 'openai/visibility': 'private'}}


TOOLS = [
    definition('list_rollout_traces', {'refresh': {'type': 'boolean'}}, public=True),
    definition('show_rollout_trace', {**TRACE, 'threadId': STRING, 'callId': STRING}, public=True),
    definition('open_rollout_viewer'),
    definition('get_rollout_binding', {'threadId': STRING}, ['threadId']),
    definition('get_rollout_overview', {**TRACE, 'beforeSeq': {'type': 'integer'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 500}}, ['traceId']),
    definition('get_rollout_delta', {**TRACE, 'revision': STRING}, ['traceId', 'revision']),
    definition('get_rollout_detail', ROW, ['traceId', 'rowId']),
    definition('get_rollout_record', {**ROW, 'callId': STRING}, ['traceId']),
    definition('get_rollout_projection', {**TRACE, 'rowIds': {'type': 'array', 'items': STRING, 'maxItems': 500}, 'beforeSeq': {'type': 'integer'}, 'afterSeq': {'type': 'integer'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 500}}, ['traceId']),
    definition('get_rollout_cell_detail', CELL, ['traceId', 'rowId', 'cellKey']),
    definition('read_rollout_cell_text', {**CELL, 'field': STRING, 'offset': {'type': 'integer'}, 'version': {'type': 'integer'}}, ['traceId', 'rowId', 'cellKey', 'field']),
    definition('get_rollout_request_info', ROW, ['traceId', 'rowId']),
    definition('search_rollout_cells', {**TRACE, 'query': STRING, 'rowIds': {'type': 'array', 'items': STRING, 'maxItems': 1000}, 'locale': STRING}, ['traceId', 'query', 'rowIds']),
    definition('read_rollout_text', {**ROW, 'section': STRING, 'itemIndex': {'type': 'integer'}, 'offset': {'type': 'integer'}}, ['traceId', 'rowId', 'section']),
    definition('add_rollout_directory', {'path': STRING, 'label': STRING}, ['path']),
]


def call(name, args, metadata=None):
    spec = next((tool for tool in TOOLS if tool['name'] == name), None)
    if spec is None or not isinstance(args, dict):
        raise TraceError('未知工具或无效参数。')
    schema = spec['inputSchema']
    if set(args) - set(schema['properties']) or any(key not in args for key in schema['required']):
        raise TraceError('工具参数不完整或包含未知字段。')
    for key, value in args.items():
        field = schema['properties'][key]
        if field['type'] == 'string' and (not isinstance(value, str) or len(value) > 4096):
            raise TraceError('字符串参数无效。')
        if field['type'] == 'integer' and (type(value) is not int or not field.get('minimum', 0) <= value <= field.get('maximum', 10**12)):
            raise TraceError('数值参数超出范围。')
        if field['type'] == 'boolean' and type(value) is not bool:
            raise TraceError('布尔参数无效。')
        if field['type'] == 'array' and (not isinstance(value, list) or len(value) > field['maxItems'] or any(not isinstance(item, str) or len(item) > 4096 for item in value)):
            raise TraceError('列表参数无效。')
    if name == 'list_rollout_traces':
        return {**STORE.list(args.get('refresh', False)), 'readerVersion': VERSION}
    if name == 'open_rollout_viewer':
        meta = metadata if isinstance(metadata, dict) else {}
        conv = meta.get('conversationId') if meta.get('host') == 'antigravity' else None
        return STORE.open(thread_id=conv)
    if name == 'show_rollout_trace':
        result = STORE.open(args.get('traceId'), args.get('threadId'))
        if result['view'] != 'trace':
            return result
        launch = {'view': 'open', 'trace': result['trace'], 'currentThreadId': result['currentThreadId']}
        if 'callId' in args:
            STORE.record(result['trace']['id'], call_id=args['callId'])
            launch['focusCallId'] = args['callId']
        return launch
    if name == 'get_rollout_binding':
        return STORE.binding(args['threadId'])
    if name == 'get_rollout_overview':
        return STORE.index(args['traceId']).overview(args.get('limit', 200), args.get('beforeSeq'))
    if name == 'get_rollout_delta':
        return STORE.index(args['traceId']).delta(args['revision'])
    if name == 'get_rollout_detail':
        return STORE.details(args['traceId'], args['rowId'])
    if name == 'get_rollout_record':
        return STORE.record(args['traceId'], args.get('rowId'), args.get('callId'))
    if name == 'get_rollout_projection':
        return STORE.projection(args['traceId'], args.get('limit', 200), args.get('beforeSeq'), args.get('afterSeq'), args.get('rowIds'))
    if name == 'get_rollout_cell_detail':
        return STORE.cell_detail(args['traceId'], args['rowId'], args['cellKey'])
    if name == 'read_rollout_cell_text':
        return STORE.cell_text(args['traceId'], args['rowId'], args['cellKey'], args['field'], args.get('offset', 0), args.get('version'))
    if name == 'get_rollout_request_info':
        return STORE.request_info(args['traceId'], args['rowId'])
    if name == 'search_rollout_cells':
        return STORE.search(args['traceId'], args['query'], args['rowIds'], args.get('locale', 'zh'))
    if name == 'read_rollout_text':
        return STORE.text(args['traceId'], args['rowId'], args['section'], args.get('itemIndex'), args.get('offset', 0))
    raise TraceError('此原生插件仅读取当前 Antigravity 会话，不支持添加 Codex 录制目录。')


def envelope(name, data):
    return {'structuredContent': data, 'content': [{'type': 'text', 'text':
            'Antigravity DSH Trace is ready.' if data.get('view') else 'Native Antigravity step data loaded.'}]}


def handle(method, params):
    if method == 'initialize':
        requested = params.get('protocolVersion')
        return {'protocolVersion': requested if requested in ('2025-06-18', '2025-11-25') else '2025-06-18', 'capabilities': {'tools': {}},
                'serverInfo': {'name': 'antigravity-dsh-trace', 'version': VERSION}}
    if method == 'ping':
        return {}
    if method == 'tools/list':
        return {'tools': TOOLS}
    if method == 'tools/call':
        try:
            return envelope(params.get('name'), call(params.get('name'), params.get('arguments', {}), params.get('_meta')))
        except (TraceError, OSError) as exc:
            message = str(exc) if isinstance(exc, TraceError) else '无法读取 Antigravity 原生步骤日志。'
            return {'isError': True, 'structuredContent': {'error': message}, 'content': [{'type': 'text', 'text': message}]}
    if method in ('resources/list', 'resources/templates/list', 'prompts/list'):
        return {'resources' if method == 'resources/list' else 'resourceTemplates' if method == 'resources/templates/list' else 'prompts': []}
    raise TraceError('不支持的 MCP 方法。')


def stdio():
    output_lock = threading.Lock()

    def process(request):
        try:
            params = request.get('params') or {}
            if not isinstance(params, dict):
                raise TraceError('Invalid params')
            response = {'jsonrpc': '2.0', 'id': request['id'], 'result': handle(request.get('method'), params)}
        except Exception as exc:
            response = {'jsonrpc': '2.0', 'id': request['id'], 'error': {'code': -32603, 'message': str(exc) if isinstance(exc, TraceError) else 'Native viewer error'}}
        with output_lock:
            sys.stdout.write(json.dumps(response, ensure_ascii=False, allow_nan=False) + '\n')
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


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-root')
    options = parser.parse_args()
    if options.data_root:
        STORE = NativeStore(options.data_root)
    stdio()
