"""Incremental, read-only index for official Codex rollout-trace bundles."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path

MAX_LOG = 256 * 1024 * 1024
MAX_PAYLOAD = 64 * 1024 * 1024
CHUNK = 48000
SUPPORTED_SCHEMAS = (1, 2)
ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")
PAYLOAD_RE = re.compile(r"^payloads/[A-Za-z0-9_.-]+\.json$")


class TraceError(ValueError):
    pass


class TraceFormatError(TraceError):
    def __init__(self, trace_id, thread_id, version):
        label=str(version) if type(version) is int else '未知'
        super().__init__(f'录制格式版本 {label} 暂不支持，请更新 Rollout Viewer。')
        self.info={'traceId':trace_id,'threadId':thread_id,'schemaVersion':version if type(version) is int else None,'message':str(self)}


def identifier(value):
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise TraceError("无效的录制或记录标识。")
    return value


def safe_file(root, relative):
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts:
        raise TraceError("录制文件路径超出允许范围。")
    path = root / rel
    part = root
    for name in rel.parts:
        part = part / name
        if part.is_symlink():
            raise TraceError("录制目录内不能包含符号链接。")
    if not path.is_file() or path.stat().st_nlink != 1:
        raise TraceError("录制文件不可用，或不是独立的普通文件。")
    return path


def read_json(path, limit=MAX_PAYLOAD):
    if path.stat().st_size > limit:
        raise TraceError("该文件超过读取上限，未截断展示。")
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TraceError("录制文件不是有效的 UTF-8 JSON。") from exc


def clean_status(value):
    return {'completed': 'complete', 'failed': 'error', 'cancelled': 'cancelled',
            'interrupted': 'cancelled', 'aborted': 'cancelled', 'running': 'running'}.get(value, value or 'running')


def preview(value, size=120):
    source = '' if value is None else str(value)
    return ' '.join(source[:max(2048,size*8)].split())[:size]


class Catalog:
    def __init__(self, config_file=None):
        codex = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
        self.config_file = Path(config_file) if config_file else codex / 'rollout-viewer/config.json'
        self.default_root = codex / 'rollout-traces'
        self.lock = threading.RLock()
        self.cache = {}
        self.issues = []
        self.last_scan = None

    def config(self):
        if not self.config_file.exists():
            return {'roots': [], 'labels': {}}
        data = read_json(self.config_file, 1024 * 1024)
        if not isinstance(data, dict):
            raise TraceError("录制目录配置格式错误。")
        return data

    def roots(self):
        roots = [self.default_root, *self.config().get('roots', [])]
        if os.environ.get('CODEX_ROLLOUT_TRACE_ROOT'):
            roots.append(os.environ['CODEX_ROLLOUT_TRACE_ROOT'])
        return list(dict.fromkeys(Path(p).expanduser().resolve() for p in roots))

    def register(self, path, label=None):
        root = Path(path).expanduser().resolve()
        if not root.is_dir():
            raise TraceError("请选择存在的录制目录。")
        with self.lock:
            config = self.config()
            roots = config.setdefault('roots', [])
            if str(root) not in roots:
                roots.append(str(root))
            if label and (root / 'manifest.json').is_file():
                meta = self.manifest(root)
                config.setdefault('labels', {})[meta['id']] = str(label)[:120]
            self.config_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temp = self.config_file.with_suffix(f'.{os.getpid()}.tmp')
            temp.write_text(json.dumps(config, ensure_ascii=False, indent=2))
            temp.chmod(0o600)
            temp.replace(self.config_file)
            self.last_scan = None
        return {'registered': True, 'path': str(root)}

    def manifest(self, path, labels=None):
        data = read_json(safe_file(path, 'manifest.json'), 1024 * 1024)
        trace_id = identifier(data.get('trace_id'))
        thread_id = identifier(data.get('root_thread_id'))
        version=data.get('schema_version')
        if type(version) is not int or version not in SUPPORTED_SCHEMAS:
            raise TraceFormatError(trace_id,thread_id,version)
        if data.get('raw_event_log') != 'trace.jsonl':
            raise TraceError('该录制的事件文件布局尚不受支持。')
        return {'id': trace_id, 'threadId': thread_id, 'startedAt': data.get('started_at_unix_ms'),
                'schemaVersion':version,
                'label': (self.config().get('labels', {}) if labels is None else labels).get(trace_id, f'任务 {thread_id[:8]}'),
                '_path': path}

    def candidates(self):
        count = 0
        for root in self.roots():
            if not root.is_dir():
                continue
            if (root / 'manifest.json').is_file():
                yield root
                continue
            for entry in os.scandir(root):
                count += 1
                if count > 10000:
                    raise TraceError("录制目录过大，请配置更具体的目录。")
                if entry.is_dir(follow_symlinks=False):
                    yield Path(entry.path)

    def list(self, force=False):
        with self.lock:
            if force or self.last_scan is None or time.monotonic() - self.last_scan > 5:
                found = {}
                issues = []
                labels = self.config().get('labels', {})
                for path in self.candidates():
                    try:
                        item = self.manifest(path, labels)
                        found[item['id']] = item
                    except TraceFormatError as exc:
                        issues.append(exc.info)
                    except TraceError as exc:
                        issues.append({'name':path.name,'message':str(exc)})
                    except OSError:
                        continue
                self.cache = found
                self.issues = issues
                self.last_scan = time.monotonic()
            return sorted(self.cache.values(), key=lambda x: x['startedAt'] or 0, reverse=True)

    def find(self, trace_id=None, thread_id=None):
        if trace_id:
            identifier(trace_id)
        if thread_id:
            identifier(thread_id)
        with self.lock:
            if trace_id and thread_id:
                item = self.find(trace_id=trace_id)
                if item and item['threadId'] != thread_id:
                    raise TraceError('录制与聊天标识不一致。')
                return item
            if thread_id:
                # A resumed chat can create several bundles with the same root.
                # Pick the newest exact-root recording, never an unrelated task.
                return next((item for item in self.list(force=True) if item['threadId']==thread_id),None)
            if trace_id and trace_id in self.cache:
                return self.cache[trace_id]
            # Explicit trace IDs resolve by bundle directory name first.
            roots = set(self.roots())
            for path in self.candidates():
                if not ((trace_id and trace_id in path.name) or path in roots):
                    continue
                try:
                    item = self.manifest(path)
                    if trace_id and item['id'] == trace_id:
                        self.cache[item['id']] = item
                        return item
                except (OSError, TraceError):
                    continue
            if trace_id:
                for item in self.list(force=True):
                    if item['id'] == trace_id:
                        return item
        return None


class BundleIndex:
    def __init__(self, meta):
        self.meta = meta
        self.path = meta['_path']
        self.lock = threading.RLock()
        self.metrics = {'logBytesRead': 0, 'payloadReads': 0, 'refreshes': 0}
        self.reset()

    def reset(self):
        self.offset = 0
        self.pending = b''
        self.signature = None
        self.last_seq = 0
        self.epoch = os.urandom(6).hex()
        self.rows = OrderedDict()
        self.threads = {}
        self.turns = {}
        self.cell_keys = {}
        self.responses = {}
        self.request_counter = 0
        self.tool_counter = 0
        self.code_counter = 0
        self.latest_requests = {}
        self.payload_refs = {}
        self.payload_cache = OrderedDict()
        self.payload_cache_size = 0
        self.context_cache = OrderedDict()
        self.text_cache = OrderedDict()
        self.text_cache_bytes = 0
        self.status = 'running'
        self.latest_time = self.meta['startedAt'] or 0
        self.unsupported = set()
        self.projection = None

    def refresh(self):
        with self.lock:
            path = safe_file(self.path, 'trace.jsonl')
            stat = path.stat()
            sig = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
            if sig == self.signature:
                return
            if stat.st_size > MAX_LOG:
                raise TraceError("事件索引超过 256 MiB 上限，未返回不完整数据。")
            if self.signature and (sig[:2] != self.signature[:2] or stat.st_size < self.offset
                                   or stat.st_size == self.offset):
                self.reset()
            with path.open('rb') as stream:
                stream.seek(self.offset)
                chunk = stream.read(MAX_LOG + 1)
            self.metrics['logBytesRead'] += len(chunk)
            self.metrics['refreshes'] += 1
            self.offset += len(chunk)
            lines = (self.pending + chunk).split(b'\n')
            self.pending = lines.pop()
            try:
                for line in lines:
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    if type(event.get('schema_version')) is not int or event.get('schema_version') != self.meta.get('schemaVersion',1) or event.get('seq') != self.last_seq + 1:
                        raise TraceError("事件版本或顺序不一致，请检查录制是否完整。")
                    self.apply(event)
                    self.last_seq = event['seq']
            except (ValueError, KeyError, TypeError) as exc:
                self.reset()
                raise TraceError("录制事件格式或顺序不一致。") from exc
            self.signature = sig

    def remember_refs(self, value):
        if isinstance(value, dict):
            if {'raw_payload_id', 'path', 'kind'} <= value.keys():
                if not isinstance(value['path'], str) or not PAYLOAD_RE.fullmatch(value['path']):
                    raise TraceError("录制中的 payload 路径不合法。")
                self.payload_refs[value['raw_payload_id']] = value
            for item in value.values():
                self.remember_refs(item)
        elif isinstance(value, list):
            for item in value:
                self.remember_refs(item)

    def row(self, key, event, **values):
        if key not in self.rows:
            self.rows[key] = {'id': key, 'seq': event['seq'], 'start': event['wall_time_unix_ms'],
                              'end': None, 'status': 'running', 'threadId': event.get('thread_id') or self.meta['threadId'],
                              'turnId': event.get('codex_turn_id'), 'parentId': None}
        row = self.rows[key]
        row.update(values)
        row['_updated'] = event['seq']
        return row

    def apply(self, event):
        payload = event['payload']
        kind = payload['type']
        now = event['wall_time_unix_ms']
        self.latest_time = max(self.latest_time, now)
        self.remember_refs(payload)
        thread = event.get('thread_id') or payload.get('thread_id') or self.meta['threadId']
        if kind == 'thread_started':
            self.threads[payload['thread_id']] = payload.get('agent_path', payload['thread_id'][:8])
        elif kind == 'codex_turn_started':
            self.turns[payload['codex_turn_id']] = {'start': now, 'threadId': thread}
        elif kind == 'inference_started':
            key = 'request:' + payload['inference_call_id']
            self.request_counter += 1
            number = self.request_counter
            self.row(key, event, type='request', kind='message', name=f'请求 #{number}',
                     model=payload.get('model'), provider=payload.get('provider_name'), threadId=payload.get('thread_id', thread),
                     turnId=payload.get('codex_turn_id'), _request=payload['request_payload'],
                     _response=None, responseId=None)
            self.latest_requests[payload.get('thread_id', thread)] = key
        elif kind in ('inference_completed', 'inference_failed', 'inference_cancelled'):
            key = 'request:' + payload['inference_call_id']
            self.row(key, event, end=now, status={'inference_completed': 'complete',
                     'inference_failed': 'error', 'inference_cancelled': 'cancelled'}[kind],
                     _response=payload.get('response_payload') or payload.get('partial_response_payload'),
                     responseId=payload.get('response_id'), _error=payload.get('error') or payload.get('reason'))
            if payload.get('response_id'):
                self.responses[payload['response_id']] = key
        elif kind == 'code_cell_started':
            self.code_counter += 1
            key = 'cell:' + thread + ':' + payload['runtime_cell_id']
            self.cell_keys[(thread, payload['runtime_cell_id'])] = key
            parent = self.latest_requests.get(thread)
            self.row(key, event, type='code', kind='tool', name='functions.exec', parentId=parent,
                     _code=payload.get('source_js', ''), _output=None, _runtimeCell=payload['runtime_cell_id'],
                     _modelCallId=payload.get('model_visible_call_id'))
        elif kind in ('code_cell_ended', 'code_cell_initial_response'):
            key = self.cell_keys.get((thread, payload['runtime_cell_id']))
            if key:
                values = {'_output': payload.get('response_payload')}
                if kind == 'code_cell_ended':
                    values.update(end=now, status=clean_status(payload.get('status')))
                self.row(key, event, **values)
        elif kind == 'tool_call_started':
            self.tool_counter += 1
            requester = payload.get('requester', {})
            parent = self.cell_keys.get((thread, requester.get('runtime_cell_id')))
            if not parent:
                parent = self.latest_requests.get(thread)
            self.row('tool:' + payload['tool_call_id'], event, type='tool',
                     kind='subtool' if requester.get('type') == 'code_cell' else 'tool',
                     name=preview(payload.get('summary', {}).get('label') or payload.get('kind', {}).get('type'), 90),
                     parentId=parent, _input=payload.get('invocation_payload'), _output=None, _runtime=[],
                     _preview=payload.get('summary', {}).get('input_preview'),
                     _modelCallId=payload.get('model_visible_call_id'))
        elif kind == 'tool_call_ended':
            self.row('tool:' + payload['tool_call_id'], event, end=now,
                     status=clean_status(payload.get('status')), _output=payload.get('result_payload'))
        elif kind in ('tool_call_runtime_started', 'tool_call_runtime_ended'):
            row = self.rows.get('tool:' + payload['tool_call_id'])
            if row and payload.get('runtime_payload'):
                row.setdefault('_runtime', []).append(payload['runtime_payload'])
                row['_updated'] = event['seq']
        elif kind == 'rollout_ended':
            self.status = clean_status(payload.get('status'))
        elif kind == 'compaction_request_started':
            self.request_counter += 1
            key = 'compaction:' + payload.get('compaction_request_id', str(event['seq']))
            self.row(key, event, type='compaction', kind='context', name='上下文压缩',
                     threadId=payload.get('thread_id', thread),turnId=payload.get('codex_turn_id'),
                     model=payload.get('model'),provider=payload.get('provider_name'),
                     _request=payload.get('request_payload'), _response=None)
        elif kind in ('compaction_request_completed', 'compaction_request_failed'):
            key = 'compaction:' + payload.get('compaction_request_id', '')
            if key in self.rows:
                self.row(key, event, end=now, status='error' if kind.endswith('failed') else 'complete',
                         _response=payload.get('response_payload'), _error=payload.get('error'))

    def public_row(self, row):
        data = {k: v for k, v in row.items() if not k.startswith('_')}
        data['version'] = row['_updated']
        data['threadLabel'] = self.threads.get(row['threadId'], row['threadId'][:8])
        data['durationMs'] = max(0, row['end'] - row['start']) if row.get('end') is not None else None
        data['error'] = row.get('status') == 'error'
        snippet = row.get('_preview')
        if isinstance(snippet, str):
            try:
                parsed = json.loads(snippet)
                snippet = parsed.get('cmd', parsed.get('command', snippet)) if isinstance(parsed, dict) else snippet
            except ValueError:
                pass
            data['summary'] = preview(snippet, 180)
        return data

    def overview(self, limit=200, before=None):
        self.refresh()
        with self.lock:
            all_rows = list(self.rows.values())
            eligible = [r for r in all_rows if before is None or r['seq'] < before]
            rows = eligible[-limit:]
            return {'trace': {k: v for k, v in self.meta.items() if not k.startswith('_')},
                    'revision': f'{self.epoch}:{self.last_seq}', 'status': self.status,
                    'origin': self.meta['startedAt'], 'latestTime': self.latest_time,
                    'totalRows': len(all_rows), 'requestCount': self.request_counter,
                    'toolCount': self.tool_counter, 'codeCellCount':self.code_counter,
                    'threads': [{'id': k, 'label': v} for k, v in self.threads.items()],
                    'rows': [self.public_row(r) for r in rows],
                    'hasEarlier': len(eligible) > len(rows), 'beforeSeq': rows[0]['seq'] if rows else None}

    def delta(self, revision):
        self.refresh()
        with self.lock:
            try:
                epoch, seq = revision.split(':')
                seq = int(seq)
            except (AttributeError, ValueError):
                epoch, seq = '', -1
            if epoch != self.epoch or seq > self.last_seq:
                return {'resync': True}
            if seq == self.last_seq:
                return {'revision': revision, 'status': self.status, 'unchanged': True,
                        'latestTime': self.latest_time, 'totalRows': len(self.rows), 'rows': []}
            changed = [r for r in self.rows.values() if r.get('_updated', 0) > seq]
            if len(changed) > 400:
                return {'resync': True}
            return {'revision': f'{self.epoch}:{self.last_seq}', 'status': self.status,
                    'unchanged': seq == self.last_seq, 'latestTime': self.latest_time,
                    'requestCount': self.request_counter, 'toolCount': self.tool_counter, 'codeCellCount':self.code_counter,
                    'threads': [{'id': k, 'label': v} for k, v in self.threads.items()],
                    'totalRows': len(self.rows), 'rows': [self.public_row(r) for r in changed]}

    def payload(self, ref):
        if not ref:
            return None
        name = ref.get('path', '')
        if not PAYLOAD_RE.fullmatch(name):
            raise TraceError("无效的 payload 引用。")
        path = safe_file(self.path, name)
        stat = path.stat()
        key = (name, stat.st_mtime_ns, stat.st_size)
        if key in self.payload_cache:
            self.payload_cache.move_to_end(key)
            return self.payload_cache[key][0]
        data = read_json(path)
        self.metrics['payloadReads'] += 1
        if stat.st_size <= 16 * 1024 * 1024:
            self.payload_cache[key] = (data, stat.st_size)
            self.payload_cache_size += stat.st_size
            while self.payload_cache and self.payload_cache_size > 32 * 1024 * 1024:
                _, (_, size) = self.payload_cache.popitem(last=False)
                self.payload_cache_size -= size
        return data

    def get_row(self, row_id):
        self.refresh()
        row = self.rows.get(row_id)
        if not row:
            raise TraceError("没有找到这条执行记录。")
        return row

    def context(self, row_id, visiting=None):
        # Iterative reconstruction avoids recursion and intermediate full copies.
        row = self.get_row(row_id)
        if row.get('type') != 'request':
            raise TraceError("这条记录不是模型请求。")
        if row_id in self.context_cache:
            self.context_cache.move_to_end(row_id)
            return self.context_cache[row_id]
        seen = set()
        chain = []
        cursor = row_id
        base = None
        complete, missing = True, None
        while cursor is not None:
            if cursor in seen:
                raise TraceError("响应链包含循环。")
            seen.add(cursor)
            if cursor in self.context_cache:
                base = self.context_cache[cursor]
                break
            current = self.rows.get(cursor)
            if not current or current.get('type') != 'request':
                complete, missing = False, cursor
                break
            raw = self.payload(current.get('_request'))
            if not isinstance(raw, dict) or not isinstance(raw.get('input'), list):
                raise TraceError("原始请求缺少 input 数组。")
            chain.append((cursor, current, raw))
            previous = raw.get('previous_response_id')
            if not previous:
                break
            cursor = self.responses.get(previous)
            if cursor is None:
                complete, missing = False, previous
                break
        items = list(base['items']) if base else []
        tools = base['tools'] if base else None
        for request_id, current, raw in reversed(chain):
            previous = raw.get('previous_response_id')
            parent_id = self.responses.get(previous) if previous else None
            if parent_id is not None:
                output = self.payload(self.rows[parent_id].get('_response')) or {}
                if not isinstance(output.get('output_items'), list):
                    complete, missing = False, previous
                else:
                    items.extend({'value': value, 'requestId': parent_id, 'origin': 'response'}
                                 for value in output['output_items'])
            if raw.get('tools') is not None:
                tools = raw['tools']
            items.extend({'value': value, 'requestId': request_id, 'origin': 'input'} for value in raw['input'])
        raw = chain[0][2]
        context = {'items':items, 'complete':complete, 'missing':missing, 'tools':tools,
                   'incremental':bool(raw.get('previous_response_id')),
                   'previousRequestId':self.responses.get(raw.get('previous_response_id')), 'raw':raw}
        if complete:
            self.context_cache[row_id] = context
            while len(self.context_cache)>16:
                self.context_cache.popitem(last=False)
        return context


def item_text(value):
    if not isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, indent=2)
    content = value.get('content')
    if isinstance(content, list) and all(isinstance(x, dict) and isinstance(x.get('text'), str) for x in content):
        return '\n\n'.join(x['text'] for x in content)
    for key in ('text', 'input', 'arguments', 'output'):
        if isinstance(value.get(key), str):
            return value[key]
    return json.dumps(value, ensure_ascii=False, indent=2)


def item_meta(entry, position, current):
    value = entry['value']
    kind = value.get('type', 'unknown') if isinstance(value, dict) else 'unknown'
    role = value.get('role') if isinstance(value, dict) else None
    if not role:
        role = 'tool' if kind.endswith('_output') else 'assistant' if kind in ('reasoning', 'function_call', 'custom_tool_call') else 'context'
    labels = {'message': '消息', 'additional_tools': '工具声明', 'custom_tool_call': '代码调用',
              'custom_tool_call_output': '代码返回值', 'function_call': '工具调用',
              'function_call_output': '工具返回值', 'reasoning': '推理项', 'compaction': '压缩项'}
    return {'index': position, 'type': kind, 'role': role, 'label': labels.get(kind, kind),
            'inherited': entry['requestId'] != current, 'origin': entry['origin'],
            'sourceRequestId': entry['requestId'], 'chars': len(item_text(value)),
            'preview': preview(item_text(value), 90) if kind == 'message' else None,
            'hasEncryptedContent': isinstance(value, dict) and bool(value.get('encrypted_content'))}


def unpack(value, code=False):
    for _ in range(6):
        if isinstance(value, str):
            try:
                value = json.loads(value)
                continue
            except ValueError:
                return value
        if isinstance(value, dict) and value.get('type') == 'code_mode_response' and 'value' in value:
            value = value['value']
        elif code and isinstance(value, dict) and set(value)=={'response'}:
            value = value['response']
        else:
            break
    return value


class Store:
    def __init__(self, config_file=None):
        self.catalog = Catalog(config_file)
        self.indexes = OrderedDict()
        self.lock = threading.RLock()

    def index(self, trace_id):
        with self.lock:
            meta = self.catalog.find(trace_id=trace_id)
            if not meta:
                problem=next((item for item in self.catalog.issues if item.get('traceId')==trace_id),None)
                if problem:raise TraceError(problem['message'])
                raise TraceError("未找到该录制。请添加其所在目录。")
            if trace_id not in self.indexes:
                self.indexes[trace_id] = BundleIndex(meta)
            self.indexes.move_to_end(trace_id)
            while len(self.indexes) > 4:
                self.indexes.popitem(last=False)
            return self.indexes[trace_id]

    def list(self, force=False):
        traces = self.catalog.list(force)
        return {'traces': [{k: v for k, v in x.items() if not k.startswith('_')} for x in traces[:100]],
                'moreAvailable': len(traces) > 100, 'defaultRoot': str(self.catalog.default_root),
                'issues':self.catalog.issues[:20],'unreadableCount':len(self.catalog.issues),
                'recordingConfigured':bool(os.environ.get('CODEX_ROLLOUT_TRACE_ROOT')),'platform':sys.platform}

    def open(self, trace_id=None, thread_id=None):
        meta = self.catalog.find(trace_id, thread_id) if trace_id or thread_id else None
        if not meta:
            result={'view': 'select', 'currentThreadId': thread_id, **self.list()}
            problem=next((item for item in self.catalog.issues if trace_id and item.get('traceId')==trace_id or thread_id and item.get('threadId')==thread_id),None)
            if problem:result['unavailableReason']=problem['message']
            return result
        return {'view': 'trace', 'currentThreadId':thread_id, **self.index(meta['id']).overview()}

    def projection(self, trace_id):
        from projection import Projection
        index = self.index(trace_id)
        index.refresh()
        with index.lock:
            if index.projection is None:
                index.projection = Projection(index)
            return index.projection

    def locate_call(self, trace_id, call_id):
        identifier(call_id)
        index=self.index(trace_id)
        index.refresh()
        with index.lock:
            matches=[row for row in index.rows.values() if row.get('type') in ('tool','code')
                     and (row.get('_modelCallId')==call_id or row['id']==call_id or row['id']=='tool:'+call_id)]
            if len(matches)!=1:
                raise TraceError('没有找到唯一对应的工具调用。请检查调用标识。')
            row=matches[0]
            return {**index.public_row(row),'callId':row.get('_modelCallId') or row['id']}

    def cell_detail(self, trace_id, row_id, cell_key):
        projector = self.projection(trace_id)
        with projector.index.lock:
            data = dict(projector.detail(row_id, cell_key))
            fields = {}
            for key in ('inputDetail','outputDetail','thinkingDetail','schemaDetail','promptDetail',
                        'previousPromptDetail','sourceBlocks','outputBlocks','messageSource','programSource'):
                if key in data and data[key] is not None:
                    value = data.pop(key)
                    is_json = not isinstance(value, str)
                    text = json.dumps(value, ensure_ascii=False, indent=2) if is_json else value
                    fields[key] = {'totalChars': len(text), 'json': is_json}
            return {'cell': data, 'fields': fields}

    def cell_text(self, trace_id, row_id, cell_key, field, offset=0, version=None):
        projector = self.projection(trace_id)
        with projector.index.lock:
            if version is not None and projector.index.get_row(row_id).get('_updated') != version:
                raise TraceError('记录已更新，请重新读取内容。')
            data = projector.detail(row_id, cell_key)
            if field not in ('inputDetail','outputDetail','thinkingDetail','schemaDetail','promptDetail',
                             'previousPromptDetail','sourceBlocks','outputBlocks','messageSource','programSource'):
                raise TraceError('未知的轨迹内容字段。')
            value = data.get(field)
            if value is None:
                return {'text':'', 'available':False, 'totalChars':0, 'nextOffset':None}
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
            return self.text_page(text, offset)

    def details(self, trace_id, row_id):
        index = self.index(trace_id)
        with index.lock:
            row = index.get_row(row_id)
            data = {'row': index.public_row(row), 'sections': []}
            if row.get('type') == 'request':
                context = index.context(row_id)
                items = context['items']
                response = index.payload(row.get('_response')) or {}
                data.update(context={k: v for k, v in context.items() if k not in ('items', 'raw', 'tools')},
                            messages=[item_meta(x, i, row_id) for i, x in enumerate(items)],
                            usage=response.get('token_usage'),
                            options={k: v for k, v in context['raw'].items() if k in ('model','reasoning','service_tier','stream','store','tool_choice','parallel_tool_calls','previous_response_id')},
                            hasTopLevelTools=context['tools'] is not None)
                data['sections'] = ['raw_request', 'response', 'tools']
            elif row.get('type') in ('tool', 'code'):
                result = unpack(index.payload(row.get('_output')),code=row.get('type')=='code')
                exit_code = result.get('exit_code') if isinstance(result, dict) else None
                data.update(exitCode=exit_code, parentId=row.get('parentId'),
                            childIds=[r['id'] for r in index.rows.values() if r.get('parentId') == row_id],
                            nextRequestId=self.next_request(index, row))
                data['sections'] = ['code' if row['type'] == 'code' else 'arguments', 'result', 'raw_result', 'runtime']
            else:
                data['sections'] = ['raw_request', 'response']
            return data

    @staticmethod
    def next_request(index, row):
        source = index.rows.get(row.get('parentId')) if row.get('kind') == 'subtool' else row
        call_id = (source or row).get('_modelCallId')
        if not call_id:
            return None
        inspected = 0
        for candidate in index.rows.values():
            if candidate.get('type') != 'request' or candidate['seq'] <= row['seq'] or candidate['threadId'] != row['threadId']:
                continue
            inspected += 1
            if inspected > 128:
                break
            payload = index.payload(candidate.get('_request')) or {}
            if any(isinstance(item, dict) and item.get('call_id') == call_id and item.get('type') in ('custom_tool_call_output','function_call_output') for item in payload.get('input', [])):
                return candidate['id']
        return None

    def text(self, trace_id, row_id, section, item_index=None, offset=0):
        index = self.index(trace_id)
        with index.lock:
            row = index.get_row(row_id)
            cache_key = (row_id, row.get('_updated'), section, item_index)
            cached = index.text_cache.get(cache_key)
            if cached is not None:
                index.text_cache.move_to_end(cache_key)
                return self.text_page(cached, offset)
            cacheable = True
            if section in ('message', 'message_json', 'full_context'):
                context = index.context(row_id)
                cacheable = context['complete']
                if section == 'full_context':
                    value = '\n\n'.join(f"[{item_meta(x, i, row_id)['role']}]\n{item_text(x['value'])}" for i, x in enumerate(context['items']))
                else:
                    if not isinstance(item_index, int) or not 0 <= item_index < len(context['items']):
                        raise TraceError("无效的上下文项。")
                    item = context['items'][item_index]['value']
                    value = item_text(item) if section == 'message' else json.dumps(item, ensure_ascii=False, indent=2)
            elif section == 'raw_request':
                value = index.payload(row.get('_request'))
            elif section == 'response':
                value = index.payload(row.get('_response'))
            elif section == 'tools':
                context = index.context(row_id)
                value = {'top_level_tools': context['tools'], 'in_history_tool_declarations':
                         [x['value'] for x in context['items'] if isinstance(x['value'], dict) and x['value'].get('type') == 'additional_tools']}
            elif section == 'code':
                value = row.get('_code')
            elif section == 'arguments':
                raw = index.payload(row.get('_input')) or {}
                payload = raw.get('payload', raw)
                value = payload.get('arguments', payload) if isinstance(payload, dict) else payload
            elif section in ('result', 'raw_result'):
                raw = index.payload(row.get('_output'))
                value = 'null' if raw is None and row.get('_output') else raw
                if section == 'result':
                    parsed = unpack(raw,code=row.get('type')=='code')
                    if isinstance(parsed, dict):
                        value = parsed.get('output', parsed)
                    elif parsed is not None:
                        value = parsed
            elif section == 'runtime':
                value = [index.payload(ref) for ref in row.get('_runtime', [])]
            else:
                raise TraceError("未知的详情类型。")
            if value is None:
                return {'text': '', 'available': False, 'totalChars': 0, 'nextOffset': None}
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
            size = len(text) * 4
            if cacheable and size <= 16 * 1024 * 1024:
                index.text_cache[cache_key] = text
                index.text_cache_bytes += size
                while index.text_cache_bytes > 32 * 1024 * 1024 or len(index.text_cache) > 40:
                    _, evicted = index.text_cache.popitem(last=False)
                    index.text_cache_bytes -= len(evicted) * 4
            return self.text_page(text, offset)

    @staticmethod
    def text_page(text, offset):
        if type(offset) is not int or offset < 0 or offset > len(text):
            raise TraceError("无效的文本分页位置。")
        end = min(len(text), offset + CHUNK)
        return {'text': text[offset:end], 'available': True, 'totalChars': len(text),
                'offset': offset, 'nextOffset': end if end < len(text) else None}
