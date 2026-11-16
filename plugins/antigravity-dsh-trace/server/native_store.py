"""Read-only Antigravity client-step logs, projected into the shared viewer contract.

These are native transcript steps, never Codex rollout recordings or raw model
requests. The builtin Swarm reader documents planner tool calls followed by
GENERIC results in call order. No request context or operation duration is
reconstructed from neighbouring steps.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import stat
import threading
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

CHUNK = 48000
MAX_LOG = 64 * 1024 * 1024
MAX_CALLS = 500
SOURCE = 'antigravity-transcript'
CONVERSATION_RE = re.compile(r'^[A-Za-z0-9_-]{1,200}$')
FIELDS = ('inputDetail', 'outputDetail', 'thinkingDetail', 'schemaDetail',
          'sourceBlocks', 'outputBlocks', 'messageSource', 'programSource')
UNAVAILABLE = 'Antigravity 原生步骤日志未记录原始模型请求、完整请求上下文或工具声明。'
UNAVAILABLE_EN = 'Antigravity native step logs do not record raw model requests, complete request context, or tool declarations.'


class TraceError(ValueError):
    pass


def conversation_id(value):
    if not isinstance(value, str) or not CONVERSATION_RE.fullmatch(value):
        raise TraceError('无效的 Antigravity 会话标识。')
    return value


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)


def content(value):
    return value if isinstance(value, str) else json_text(value) if value is not None else ''


def preview(value, maximum=160):
    return ' '.join(content(value)[:4096].split())[:maximum]


def unavailable(reason=UNAVAILABLE, reason_en=UNAVAILABLE_EN):
    return {'available': False, 'text': '', 'totalChars': 0, 'nextOffset': None,
            'source': SOURCE, 'reason': reason, 'reasonEn': reason_en}


def chunk(value, offset=0):
    text = content(value)
    return {'available': True, 'text': text[offset:offset + CHUNK],
            'totalChars': len(text), 'nextOffset': offset + CHUNK if offset + CHUNK < len(text) else None,
            'source': SOURCE}


def recorded_time(value):
    """Only parse an explicitly timezone-qualified ISO timestamp; never infer time."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.timestamp() * 1000 if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def status_of(value):
    return {'DONE': 'complete', 'ERROR': 'error', 'RUNNING': 'running',
            'CANCELLED': 'cancelled', 'CANCELED': 'cancelled'}.get(value, 'running')


def default_data_root():
    configured = os.environ.get('ANTIGRAVITY_NATIVE_DATA_ROOT')
    if configured:
        return Path(configured).expanduser().absolute()
    # A plugin can also run under another Antigravity product's app-data root.
    runtime_data = os.environ.get('ANTIGRAVITY_EXECUTABLE_DATA_DIR')
    if runtime_data:
        for parent in Path(runtime_data).expanduser().absolute().parents:
            if parent.name == 'sidecar_data':
                return parent.parent
    return Path.home() / '.gemini' / 'antigravity'


class NativeIndex:
    def __init__(self, app_data, conv):
        self.app_data = Path(app_data).expanduser().absolute()
        self.conv = conversation_id(conv)
        self.lock = threading.RLock()
        self.rows = OrderedDict()
        self.epoch = secrets.token_hex(8)
        self.revision = 0
        self._stamp = None
        self._path = None
        self._events = OrderedDict()
        self.source_file = None
        self.partial_tail = False
        self.duplicate_steps = 0
        self.compact_fallback = False

    @property
    def trace_id(self):
        return 'native:' + self.conv

    def _source_path(self):
        relative = Path('brain') / self.conv / '.system_generated' / 'logs'
        current = self.app_data
        for component in relative.parts:
            current = current / component
            if current.is_symlink():
                raise TraceError('Antigravity 日志路径不能包含符号链接。')
        for name in ('transcript_full.jsonl', 'transcript.jsonl'):
            candidate = current / name
            if candidate.is_symlink():
                raise TraceError('Antigravity 日志不能是符号链接。')
            if candidate.exists():
                info = candidate.stat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise TraceError('Antigravity 日志必须是独立的普通文件。')
                return candidate, info
        return None, None

    def refresh(self):
        with self.lock:
            path, info = self._source_path()
            stamp = (str(path), info.st_ino, info.st_size, info.st_mtime_ns) if info else None
            if stamp == self._stamp:
                return
            if info and info.st_size > MAX_LOG:
                raise TraceError('Antigravity 日志超过 64 MiB 读取上限，未截断展示。')
            raw = b''
            if path:
                fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
                try:
                    opened = os.fstat(fd)
                    if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                        raise TraceError('Antigravity 日志必须是独立的普通文件。')
                    with os.fdopen(fd, 'rb', closefd=False) as stream:
                        raw = stream.read(MAX_LOG + 1)
                finally:
                    os.close(fd)
                if len(raw) > MAX_LOG:
                    raise TraceError('Antigravity 日志超过 64 MiB 读取上限，未截断展示。')
            events = OrderedDict()
            partial = False
            duplicates = 0
            lines = raw.splitlines()
            for number, line in enumerate(lines):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except (ValueError, UnicodeError):
                    if number == len(lines) - 1 and not raw.endswith(b'\n'):
                        partial = True
                        break
                    raise TraceError(f'Antigravity 日志第 {number + 1} 行不是有效的 JSON。')
                if (not isinstance(event, dict) or type(event.get('step_index')) is not int
                        or not 0 <= event['step_index'] <= 10**9 or not isinstance(event.get('type'), str)):
                    raise TraceError(f'Antigravity 日志第 {number + 1} 行的步骤结构不受支持。')
                if event['step_index'] in events:
                    duplicates += 1
                events[event['step_index']] = event
            events = OrderedDict(sorted(events.items()))
            candidate_rows = self._project(events)
            removed = set(self.rows) - set(candidate_rows)
            # Rewrites must invalidate UI cells that disappeared or changed order.
            old_order = [key for key in self.rows if key in candidate_rows]
            new_order = [key for key in candidate_rows if key in self.rows]
            reset = removed or old_order != new_order or self._path is not None and path != self._path
            if reset:
                self.epoch = secrets.token_hex(8)
                self.revision = 0
            for key, row in candidate_rows.items():
                old = self.rows.get(key)
                comparable = {k: v for k, v in old.items() if k != 'version'} if old else None
                if reset or comparable != row:
                    self.revision += 1
                    row['version'] = self.revision
                else:
                    row['version'] = old['version']
            self.rows = candidate_rows
            self._events = events
            self._stamp, self._path = stamp, path
            self.source_file = path.name if path else None
            self.compact_fallback = bool(path and path.name != 'transcript_full.jsonl')
            self.partial_tail, self.duplicate_steps = partial, duplicates

    def _project(self, events):
        rows = OrderedDict()
        pending = []
        turn, planner, planner_count = 0, 0, 0
        for index, event in events.items():
            kind = event['type']
            if kind == 'USER_INPUT':
                turn += 1
                planner = 0
                pending = []
            if kind == 'PLANNER_RESPONSE':
                planner += 1
                pending = []
            base = {'id': f'step:{index}', 'seq': (index + 1) * 1000,
                    'threadId': self.conv, 'turn': turn or None, 'step': planner,
                    'group': f'步骤 {planner}' if planner else '', 'source': SOURCE,
                    'nativeStepIndex': index, 'nativeType': kind, 'nativeStatus': event.get('status'),
                    'status': status_of(event.get('status')), 'start': recorded_time(event.get('created_at')),
                    'end': None, '_event': event, 'type': 'native-step'}
            if kind == 'GENERIC' and pending:
                target = pending[0]
                explicit_name = event.get('tool_name', event.get('toolName'))
                explicit_id = event.get('call_id', event.get('callId'))
                recorded_id = target['_call'].get('id', target['_call'].get('call_id'))
                if ((not explicit_name or explicit_name == target['name'])
                        and (not explicit_id or explicit_id == recorded_id)):
                    pending.pop(0)
                    target['_result'] = event
                    target['status'] = status_of(event.get('status'))
                    target['nativeResultStepIndex'] = index
                    target['nativeResultStatus'] = event.get('status')
                    target['association'] = 'native-transcript-call-order'
                    continue
            rows[base['id']] = base
            if kind == 'PLANNER_RESPONSE':
                base['type'] = 'native-planner'
                planner_count += 1
                base['number'] = planner_count
                base['_toolRows'] = []
                calls = event.get('tool_calls', [])
                if calls is None:
                    calls = []
                if not isinstance(calls, list) or len(calls) > MAX_CALLS:
                    raise TraceError('Antigravity 步骤的工具调用列表不受支持或超过读取上限。')
                for ordinal, call in enumerate(calls):
                    if not isinstance(call, dict) or not isinstance(call.get('name'), str):
                        continue  # The original unrecognized call stays in the raw native step.
                    call_id = f'native-call:{self.conv}:{index}:{ordinal}'
                    tool = {**base, 'id': f'tool:{index}:{ordinal}', 'seq': base['seq'] + ordinal + 1,
                            'type': 'native-tool', 'name': call['name'], '_call': call,
                            'callId': call_id, 'status': 'running', '_result': None,
                            'nativeCallOrdinal': ordinal, 'start': None}
                    rows[tool['id']] = tool
                    base['_toolRows'].append(tool['id'])
                    pending.append(tool)
            elif kind not in ('GENERIC', 'SYSTEM_MESSAGE'):
                pending = []
        return rows

    def meta(self):
        times = [row['start'] for row in self.rows.values() if row['start'] is not None]
        timestamps = [row['_event'].get('created_at') for row in self.rows.values() if row['start'] is not None]
        precision = 'seconds' if timestamps and all('.' not in value for value in timestamps) else 'source'
        return {'id': self.trace_id, 'threadId': self.conv, 'label': 'Antigravity ' + self.conv[:8],
                'source': SOURCE, 'sourceFile': self.source_file, 'compactFallback': self.compact_fallback,
                'startedAt': min(times) if times else None, 'timestampSemantics': 'native-step-created-at',
                'timestampPrecision': precision, 'isNativeTranscript': True,
                'capabilities': {'rawModelRequest': False, 'fullRequestContext': False,
                                 'toolSchemas': False, 'operationDurations': False}}

    def state(self):
        if not self._events:
            return 'running'
        last = next(reversed(self._events.values()))
        if last.get('type') == 'PLANNER_RESPONSE' and not last.get('tool_calls'):
            return status_of(last.get('status'))
        if last.get('type') == 'ERROR_MESSAGE':
            return 'error'
        return 'running'

    def summary(self):
        times = [row['start'] for row in self.rows.values() if row['start'] is not None]
        return {'revision': f'{self.epoch}:{self.revision}', 'status': self.state(),
                'origin': min(times) if times else None, 'latestTime': max(times) if times else None,
                'totalRows': len(self.rows),
                'requestCount': sum(row['type'] == 'native-planner' for row in self.rows.values()),
                'toolCount': sum(row['type'] == 'native-tool' for row in self.rows.values()),
                'codeCellCount': 0, 'threads': [{'id': self.conv, 'label': 'Antigravity'}],
                'source': SOURCE, 'sourceFile': self.source_file, 'partialTail': self.partial_tail,
                'compactFallback': self.compact_fallback}

    @staticmethod
    def public_row(row):
        return {k: v for k, v in row.items() if not k.startswith('_')}

    def overview(self, limit=200, before=None):
        self.refresh()
        with self.lock:
            eligible = [row for row in self.rows.values() if before is None or row['seq'] < before]
            rows = eligible[-limit:]
            return {'trace': self.meta(), **self.summary(), 'rows': [self.public_row(row) for row in rows],
                    'hasEarlier': len(eligible) > len(rows), 'beforeSeq': rows[0]['seq'] if rows else None}

    def delta(self, revision):
        self.refresh()
        with self.lock:
            try:
                epoch, number = revision.split(':')
                number = int(number)
            except (AttributeError, ValueError):
                return {'resync': True}
            if epoch != self.epoch or number > self.revision or number < 0:
                return {'resync': True}
            changed = [row for row in self.rows.values() if row['version'] > number]
            if len(changed) > 400:
                return {'resync': True}
            return {**self.summary(), 'unchanged': not changed,
                    'rows': [self.public_row(row) for row in changed]}

    def row(self, row_id):
        try:
            return self.rows[row_id]
        except (KeyError, TypeError):
            raise TraceError('没有找到这条 Antigravity 原生步骤。')

    def cells(self, row, detailed=False):
        event = row['_event']
        base = {key: row[key] for key in ('seq', 'turn', 'step', 'group', 'threadId', 'version')}
        base.update(rowId=row['id'], timeSeconds=None, startedAt=row['start'], source=SOURCE,
                    timestampSemantics='native-step-created-at', isError=row['status'] in ('error', 'cancelled'),
                    detailsPending=not detailed, slot=0)
        text = content(event.get('content'))
        source = {'source': SOURCE, 'type': event['type'], 'role': event.get('source'),
                  'metadata': {key: event[key] for key in ('step_index', 'created_at', 'status') if key in event}}
        if row['type'] == 'native-tool':
            result = row['_result']
            result_text = content(result.get('content', result.get('error'))) if result else ''
            if result and not result_text:
                result_text = json_text(result)
            base.update(cellKey='tool', kind='tool', text=row['name'], toolName=row['name'],
                        callId=row['callId'], inputDetail=content(row['_call'].get('args')) if detailed else ' ',
                        outputDetail=result_text if detailed else ' ' if result else '', schemaDetail='',
                        result=preview(result_text),
                        outputBlocks=[{'type': 'text', 'content': result_text}] if detailed and result else [])
            if result:
                base['resultSeq'] = row['seq']
        elif event['type'] == 'USER_INPUT':
            base.update(cellKey='message', kind='user', text='', opensTurn=True,
                        previewMarkdown=text[:2048], inputDetail=text if detailed else ' ', messageSource=source,
                        sourceBlocks=[{'type': 'text', 'content': text}] if detailed else [])
        elif row['type'] == 'native-planner':
            calls = [self.rows[key] for key in row['_toolRows']]
            blocks = [{'type': 'text', 'content': text}] if detailed and text else []
            blocks += [{'type': 'tool-call', 'content': content(tool['_call'].get('args')) if detailed else '',
                        'callId': tool['callId'], 'toolName': tool['name']} for tool in calls]
            tokens = event.get('output_tokens')
            has_tokens = type(tokens) is int and tokens >= 0
            base.update(cellKey='assistant', kind='message', text='（仅工具调用）' if calls and not text else '',
                        previewMarkdown=(text or content(event.get('thinking')))[:2048],
                        outputDetail=text if detailed else ' ' if text else '',
                        thinkingDetail=content(event.get('thinking')) if detailed else ' ' if event.get('thinking') else '',
                        sourceBlocks=blocks, messageSource=source,
                        assistantMetrics={'timingRecorded': False, 'stepStartTime': None, 'firstTokenTime': None,
                                          'completedTime': None, 'usageProvided': has_tokens,
                                          'outputTokens': tokens if has_tokens else None})
            if has_tokens:
                base['output'] = tokens
        else:
            if not text:
                text = content(event.get('error')) or json_text(event)
            base.update(cellKey='native', kind='context', text=event['type'], previewMarkdown=text[:2048],
                        inputDetail=text if detailed else ' ', messageSource=source,
                        sourceBlocks=[{'type': 'text', 'content': text}] if detailed else [])
        base['recordId'] = row['id'] + ':' + base['cellKey']
        return [base]

    def request_info(self, row):
        if row['type'] != 'native-planner':
            raise TraceError('这条原生步骤不是 planner 响应。')
        value = {key: row[key] for key in ('seq', 'turn', 'step', 'group', 'number', 'status', 'version')}
        if value['status'] == 'cancelled':
            value['status'] = 'error'
        value.update(rowId=row['id'], source=SOURCE, startedAt=row['start'], completedAt=None,
                     timestampSemantics='native-step-created-at', resultSeq=row['seq'])
        if isinstance(row['_event'].get('model'), str):
            value['model'] = row['_event']['model']
        # Input/cache semantics are not documented as disjoint token buckets.
        tokens = row['_event'].get('output_tokens')
        if type(tokens) is int and tokens >= 0:
            value['usage'] = {'output': tokens}
        return value


class NativeStore:
    def __init__(self, app_data=None):
        self.app_data = Path(app_data) if app_data is not None else default_data_root()
        self.indexes = OrderedDict()
        self.lock = threading.RLock()

    def index(self, trace_id):
        if not isinstance(trace_id, str) or not trace_id.startswith('native:'):
            raise TraceError('此插件仅读取 Antigravity 原生步骤，不接受 Codex 录制标识。')
        conv = conversation_id(trace_id[len('native:'):])
        with self.lock:
            if conv not in self.indexes:
                self.indexes[conv] = NativeIndex(self.app_data, conv)
            self.indexes.move_to_end(conv)
            while len(self.indexes) > 4:
                self.indexes.popitem(last=False)
            index = self.indexes[conv]
        index.refresh()
        return index

    def list(self, refresh=False):
        brain = self.app_data / 'brain'
        traces, issues = [], []
        if brain.is_symlink():
            raise TraceError('Antigravity brain 目录不能是符号链接。')
        if brain.is_dir():
            for path in sorted(brain.iterdir()):
                if path.is_symlink() or not path.is_dir() or not CONVERSATION_RE.fullmatch(path.name):
                    continue
                try:
                    index = self.index('native:' + path.name)
                    if index.source_file:
                        traces.append(index.meta())
                except (TraceError, OSError) as exc:
                    issues.append({'threadId': path.name, 'message': str(exc) if isinstance(exc, TraceError) else '无法读取原生日志。'})
        return {'traces': traces[:100], 'moreAvailable': len(traces) > 100, 'source': SOURCE,
                'issues': issues[:20], 'unreadableCount': len(issues)}

    def open(self, trace_id=None, thread_id=None):
        if trace_id is not None:
            index = self.index(trace_id)
            if thread_id is not None and conversation_id(thread_id) != index.conv:
                raise TraceError('原生步骤与会话标识不一致。')
        elif thread_id is not None:
            index = self.index('native:' + conversation_id(thread_id))
        else:
            return {'view': 'select', 'currentThreadId': None, 'source': SOURCE,
                    'unavailableReason': '未收到 Antigravity 当前面板的会话标识。',
                    'unavailableReasonEn': 'The Antigravity pane did not provide its conversation ID.'}
        if not index.rows:
            return {'view': 'select', 'currentThreadId': index.conv, 'source': SOURCE}
        return {'view': 'trace', 'currentThreadId': index.conv, **index.overview()}

    def binding(self, thread_id):
        index = self.index('native:' + conversation_id(thread_id))
        return {'currentThreadId': index.conv, 'trace': index.meta() if index.rows else None, 'source': SOURCE}

    def projection(self, trace_id, limit=200, before=None, after=None, row_ids=None):
        index = self.index(trace_id)
        with index.lock:
            eligible = [row for row in index.rows.values() if (before is None or row['seq'] < before)
                        and (after is None or row['seq'] > after) and (row_ids is None or row['id'] in row_ids)]
            rows = eligible if row_ids is not None else eligible[-limit:] if after is None else eligible[:limit]
            return {'cells': [cell for row in rows for cell in index.cells(row)],
                    'requestNumbers': [index.request_info(row) for row in rows if row['type'] == 'native-planner'],
                    'rowIds': [row['id'] for row in rows], 'hasEarlier': len(eligible) > len(rows),
                    'beforeSeq': rows[0]['seq'] if rows else None, 'afterSeq': rows[-1]['seq'] if rows else None,
                    'source': SOURCE}

    def cell_detail(self, trace_id, row_id, cell_key):
        index = self.index(trace_id)
        with index.lock:
            cell = self._cell(index, row_id, cell_key)
            fields = {}
            for field in FIELDS:
                if field in cell and cell[field] is not None:
                    value = cell.pop(field)
                    fields[field] = {'totalChars': len(content(value)), 'json': not isinstance(value, str)}
            return {'cell': cell, 'fields': fields, 'source': SOURCE}

    @staticmethod
    def _cell(index, row_id, cell_key):
        cell = index.cells(index.row(row_id), detailed=True)[0]
        if cell['cellKey'] != cell_key:
            raise TraceError('没有找到这条 Antigravity 轨迹单元。')
        return cell

    def cell_text(self, trace_id, row_id, cell_key, field, offset=0, version=None):
        if field not in FIELDS:
            raise TraceError('未知的轨迹内容字段。')
        index = self.index(trace_id)
        with index.lock:
            row = index.row(row_id)
            if version is not None and row['version'] != version:
                raise TraceError('记录已更新，请重新读取内容。')
            value = self._cell(index, row_id, cell_key).get(field)
            return chunk(value, offset) if value is not None else unavailable()

    def details(self, trace_id, row_id):
        index = self.index(trace_id)
        with index.lock:
            row = index.row(row_id)
            return {'row': index.public_row(row), 'source': SOURCE, 'messages': [],
                    'context': {'available': False, 'complete': False, 'reason': UNAVAILABLE,
                                'reasonEn': UNAVAILABLE_EN},
                    'nativeStep': row['_event'], 'hasRawRequest': False}

    def text(self, trace_id, row_id, section, item_index=None, offset=0):
        index = self.index(trace_id)
        with index.lock:
            row = index.row(row_id)
            if section in ('full_context', 'raw_request', 'tools', 'code'):
                return unavailable()
            if section in ('response', 'runtime'):
                value = row['_event']
            elif section in ('result', 'raw_result') and row['type'] == 'native-tool':
                value = row['_result']
            elif section == 'arguments' and row['type'] == 'native-tool':
                value = row['_call'].get('args')
            elif section in ('message', 'message_json') and item_index in (None, 0):
                value = row['_event'].get('content') if section == 'message' else row['_event']
            else:
                value = None
            return chunk(value, offset) if value is not None else unavailable()

    def record(self, trace_id, row_id=None, call_id=None):
        index = self.index(trace_id)
        with index.lock:
            if (row_id is None) == (call_id is None):
                raise TraceError('请选择记录标识或调用标识之一。')
            if row_id is not None:
                row = index.row(row_id)
            else:
                matches = [row for row in index.rows.values() if row.get('callId') == call_id]
                if len(matches) != 1:
                    raise TraceError('没有找到唯一对应的原生工具调用。')
                row = matches[0]
            return {'row': index.public_row(row)}

    def request_info(self, trace_id, row_id):
        index = self.index(trace_id)
        with index.lock:
            return {'request': index.request_info(index.row(row_id))}

    def search(self, trace_id, query, row_ids, locale='zh'):
        index = self.index(trace_id)
        needle = query.casefold()
        matches = []
        with index.lock:
            for row_id in row_ids:
                row = index.row(row_id)
                for cell in index.cells(row, detailed=True):
                    haystack = '\n'.join(content(cell.get(key)) for key in ('text', 'toolName', *FIELDS))
                    if needle in haystack.casefold():
                        matches.append(cell['recordId'])
        return {'matches': matches}
