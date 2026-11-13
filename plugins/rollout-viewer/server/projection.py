"""Codex recording → DSH trajectory records. Bodies remain app-only and lazy."""
from __future__ import annotations

import hashlib
import base64
import json
from collections import OrderedDict

from store import TraceError, item_text, preview, unpack


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2)


def usage(value):
    if not isinstance(value, dict):
        return None
    keys = {'cacheRead': 'cached_input_tokens', 'cacheWrite': 'cache_write_input_tokens',
            'output': 'output_tokens', 'reasoning': 'reasoning_output_tokens'}
    result = {key: value[source] for key, source in keys.items()
              if isinstance(value.get(source), (int, float))}
    if isinstance(value.get('input_tokens'), (int, float)):
        # DSH's input/cache buckets are disjoint. Codex's input_tokens includes cache.
        result['input'] = max(0, value['input_tokens'] - result.get('cacheRead', 0) - result.get('cacheWrite', 0))
    return result or None


def catalog_tools(value):
    """Keep complete recorded declarations, normalizing only DSH's display shape."""
    tools = []
    for entry in value or []:
        if not isinstance(entry, dict):
            continue
        if entry.get('type') == 'namespace':
            children = catalog_tools(entry.get('tools'))
            tools.extend({**tool,'qualifiedName': f'{entry.get("name", "")}.{tool["name"]}'} for tool in children)
            continue
        tool = entry.get('function', entry)
        if isinstance(tool, dict):
            tools.append({**tool, 'name': tool.get('name', entry.get('type', 'unknown')),
                          'parameters': tool.get('parameters', tool.get('input_schema', tool.get('format', {})))})
    return tools


def source_blocks(item, owner, label):
    """Preserve block order, original roles, attachments, and publicly returned text."""
    blocks = []
    contents = item.get('content', []) if isinstance(item, dict) else []
    if isinstance(contents, str):
        contents = [{'type': 'text', 'text': contents}]
    for position, block in enumerate(contents):
        if not isinstance(block, dict):
            blocks.append({'type': 'unknown', 'content': json_text(block)})
            continue
        kind = block.get('type', 'unknown')
        if isinstance(block.get('text'), str):
            blocks.append({'type': 'text', 'content': block['text']})
        elif kind in ('input_image', 'output_image', 'image'):
            url = block.get('image_url', block.get('url'))
            if isinstance(url, dict):
                url = url.get('url')
            asset_id = f'{owner}:{label}:{position}'
            attachment = {'attachmentId': asset_id,
                          'name': block.get('filename', block.get('name', f'图片 {position + 1}'))}
            for key in ('width', 'height'):
                if key in block:
                    attachment[key] = block[key]
            if isinstance(url, str) and url.startswith('data:image/'):
                attachment['recordedUrl'] = url
                header, _, encoded = url.partition(',')
                attachment['mediaType'] = header[5:].split(';')[0]
                if ';base64' in header:
                    try:
                        data = base64.b64decode(encoded, validate=True)
                        attachment['bytes'] = len(data)
                        attachment['attachmentId'] = hashlib.sha256(data).hexdigest()
                        if data.startswith(b'\x89PNG\r\n\x1a\n') and len(data)>=24:
                            attachment.setdefault('width',int.from_bytes(data[16:20],'big'))
                            attachment.setdefault('height',int.from_bytes(data[20:24],'big'))
                    except ValueError:
                        pass
            # Never make a network request or read an arbitrary local path from a trace.
            blocks.append({'type': 'image', 'content': json_text(block), 'attachment': attachment})
        elif kind in ('input_file', 'file'):
            ref = {'attachmentId': f'{owner}:{label}:{position}',
                   'name': block.get('filename', block.get('name', '未命名文件'))}
            for source, target in [('mime_type', 'mediaType'), ('mimeType', 'mediaType'), ('size', 'bytes'),('bytes','bytes')]:
                if source in block:
                    ref[target] = block[source]
            blocks.append({'type': 'file', 'content': json_text(block), 'file': ref})
        else:
            blocks.append({'type': kind, 'content': json_text(block)})
    return blocks


class Projection:
    def __init__(self, index):
        self.index = index
        self.cache = OrderedDict()
        self.detail_cache = OrderedDict()
        self.detail_bytes = 0

    def requests(self):
        return [row for row in self.index.rows.values() if row.get('type') in ('request', 'compaction')]

    def location(self, row):
        turn_keys = list(self.index.turns)
        key = row.get('turnId')
        turn = turn_keys.index(key) + 1 if key in turn_keys else (1 if key and row.get('type') != 'compaction' else None)
        requests = self.requests()
        parent = row
        visited = set()
        while parent and parent.get('type') not in ('request', 'compaction'):
            if parent['id'] in visited:
                break
            visited.add(parent['id'])
            parent = self.index.rows.get(parent.get('parentId'))
        if not parent or parent.get('type') not in ('request', 'compaction'):
            parent = next((candidate for candidate in reversed(requests)
                           if candidate['seq'] < row['seq'] and candidate['threadId'] == row['threadId']), row)
        if parent.get('type') == 'compaction':
            return turn, 0, f'压缩 {parent["seq"]}', parent
        siblings = [candidate for candidate in requests if candidate.get('type') == 'request'
                    and candidate.get('turnId') == parent.get('turnId') and candidate['threadId'] == parent['threadId']]
        step = next((position + 1 for position, candidate in enumerate(siblings) if candidate['id'] == parent['id']), 1)
        return turn, step, f'第 {step} 步', parent

    def request_info(self, row, cumulative=False):
        turn, step, group, _ = self.location(row)
        request = self.index.payload(row.get('_request')) or {}
        response = self.index.payload(row.get('_response')) or {}
        options = {key: value for key, value in request.items() if key not in ('input', 'tools')}
        data = {'rowId': row['id'], 'version':row.get('_updated'), 'seq': row['seq'], 'turn': turn, 'step': step,
                'group': group, 'number': self.requests().index(row) + 1,
                'status': 'error' if row['status'] in ('error', 'cancelled') else row['status'],
                'startedAt': row['start'], 'completedAt': row.get('end'),
                'model': row.get('model', request.get('model')), 'requestConfig': options}
        if row.get('provider'):
            data['provider'] = row['provider']
        if row.get('end') is not None:
            data['resultSeq'] = row['seq']
        if row.get('_error'):
            data['error'] = row['_error'] if isinstance(row['_error'], str) else json_text(row['_error'])
        if row.get('type') == 'compaction':
            data.update(purpose='compaction', step=0)
        reported = usage(response.get('token_usage'))
        if reported:
            data['usage'] = reported
        if cumulative:
            total = {}
            for candidate in self.requests():
                if candidate['seq'] > row['seq']:
                    break
                if candidate['threadId'] != row['threadId']:
                    continue
                value = self.index.payload(candidate.get('_response')) or {}
                for key, amount in (usage(value.get('token_usage')) or {}).items():
                    total[key] = total.get(key, 0) + amount
            if total:
                data['cumulativeUsage'] = total
        return data

    def prompt(self, row):
        context = self.index.context(row['id'])
        entries = [entry['value'] for entry in context['items'] if isinstance(entry['value'], dict)]
        system = '\n\n'.join(f'[{item.get("role", "developer")}]\n{item_text(item)}'
                             for item in entries if item.get('role') in ('system', 'developer') and item.get('type') != 'additional_tools')
        tools = catalog_tools(context.get('tools'))
        for item in entries:
            if item.get('type') == 'additional_tools':
                tools.extend(catalog_tools(item.get('tools')))
        return {'system': system, 'tools': tools, 'config': self.request_info(row)['requestConfig']}

    def cells(self, row):
        key = (row['id'], row.get('_updated'))
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        turn, step, group, parent = self.location(row)
        duration = max(0, row['end'] - row['start']) / 1000 if row.get('end') is not None else None
        base = {'rowId': row['id'], 'seq': row['seq'], 'turn': turn, 'step': step, 'group': group,
                'threadId': row['threadId'], 'version': row.get('_updated'),
                'sourceSeq': row['seq'], 'startedAt': row['start'], 'timeSeconds': duration,
                'isError': row['status'] in ('error', 'cancelled'), 'detailsPending': True}
        cells = []
        if row.get('type') == 'request':
            raw = self.index.payload(row.get('_request')) or {}
            inputs = raw.get('input', [])
            response = self.index.payload(row.get('_response')) or {}
            previous = next((candidate for candidate in reversed(self.requests())
                             if candidate['threadId'] == row['threadId'] and candidate['seq'] < row['seq'] and candidate.get('type') == 'request'), None)
            # A full request can replay an earlier prefix. Retain only newly introduced items.
            skip = 0
            if not raw.get('previous_response_id') and previous:
                before = self.index.context(previous['id'])
                output = self.index.payload(previous.get('_response')) or {}
                known = [entry['value'] for entry in before['items']] + output.get('output_items', [])
                while skip < min(len(inputs), len(known)) and inputs[skip] == known[skip]:
                    skip += 1
            introduced = list(enumerate(inputs))[skip:]
            has_prompt = any(isinstance(item, dict) and item.get('role') in ('developer', 'system') for _, item in introduced) or raw.get('tools') is not None
            if has_prompt:
                prompt = self.prompt(row)
                prior = self.prompt(previous) if previous else None
                if prior is None or prompt['system'] != prior['system'] or prompt['tools'] != prior['tools']:
                    cells.append({**base, 'sourceSeq':None, 'cellKey': 'prompt', 'kind': 'system', 'text': '指令与工具更新' if prior else '指令与工具目录',
                                  'timeSeconds': 0, 'promptDetail': {'system': '', 'tools': [], 'config': {}},
                                  **({'previousPromptDetail': {'system': '', 'tools': [], 'config': {}}} if prior else {})})
            for position, item in introduced:
                if not isinstance(item, dict) or item.get('type') not in ('message', 'input_message') or item.get('role') in ('system', 'developer', 'assistant'):
                    continue
                text = item_text(item)
                context = item.get('role') != 'user' or text.lstrip().startswith(('<environment_context>', '<turn_aborted>', '<codex_internal_context'))
                blocks = source_blocks(item, row['id'], f'input-{position}')
                attachments = [block for block in blocks if 'attachment' in block or 'file' in block]
                # Metadata counts are sufficient to paint the row without shipping a base64 image.
                source = text if not attachments else '\n'.join(b['content'] for b in blocks if b['type'] == 'text')
                images = sum('attachment' in block for block in attachments)
                files = sum('file' in block for block in attachments)
                summary = ' · '.join(part for part in [f'图片 ×{images}' if images else '',f'文件 ×{files}' if files else ''] if part)
                cells.append({**base, 'sourceSeq':None, 'cellKey': f'input:{position}', 'kind': 'context' if context else 'user',
                              'text': summary, 'previewMarkdown':source[:2048], 'opensTurn': not context, 'inputDetail': ' ', 'timeSeconds': 0,
                              'messageSource': {'role': item.get('role'), 'type': item.get('type')},
                              'sourceBlocks': [{**b, 'content': '', **({'attachment': {k:v for k,v in b['attachment'].items() if k != 'recordedUrl'}} if b.get('attachment') else {})} for b in attachments]})
            outputs = response.get('output_items', [])
            messages = [item for item in outputs if isinstance(item, dict) and item.get('type') == 'message']
            reasoning = [item for item in outputs if isinstance(item, dict) and item.get('type') == 'reasoning']
            returned_text = '\n\n'.join(item_text(item) for item in messages)
            publicly_returned = '\n\n'.join(part.get('text', '') for item in reasoning for part in item.get('summary', []) if isinstance(part, dict))
            facts = usage(response.get('token_usage')) or {}
            cells.append({**base, 'cellKey': 'assistant', 'kind': 'message', 'text': '' if returned_text else ('（仅工具调用）' if outputs else ''),
                          **({'previewMarkdown':returned_text[:2048]} if returned_text else {}),
                          'outputDetail': ' ' if messages else '', 'thinkingDetail': ' ' if publicly_returned else '',
                          'assistantMetrics': {'timingRecorded': True, 'stepStartTime': row['start'], 'firstTokenTime': None,
                                               'completedTime': row.get('end'), 'usageProvided': bool(facts), 'outputTokens': facts.get('output')},
                          **{target: facts[source] for source, target in [('input','input'),('cacheRead','cacheRead'),('cacheWrite','cacheWrite'),('output','output'),('reasoning','think')] if source in facts}})
        elif row.get('type') == 'compaction':
            cells.append({**base, 'cellKey': 'compaction', 'kind': 'compacted', 'text': '上下文压缩', 'outputDetail': ' '})
        else:
            raw = self.index.payload(row.get('_input')) or {}
            result = unpack(self.index.payload(row.get('_output')))
            program = row.get('type') == 'code'
            name = 'functions.exec' if program else raw.get('tool_name', row.get('name', 'unknown'))
            output = result.get('output', result) if isinstance(result, dict) else result
            output_text = output if isinstance(output, str) else json_text(output) if output is not None else ''
            cells.append({**base, 'cellKey': 'tool', 'kind': row.get('kind', 'tool'), 'toolName': name,
                          'callId': row.get('_modelCallId') or row['id'], **({'resultSeq':row['seq']} if row.get('_output') else {}),
                          'text': f'{name} · {preview(row.get("_code") or row.get("_preview"), 100)}',
                          'inputDetail': ' ', 'outputDetail': ' ' if row.get('_output') else '', 'schemaDetail': '',
                          'result': preview(output_text, 160), 'programSource': ' ' if program else None})
            if program:
                cells[-1]['programDescription'] = preview(row.get('_code'), 120)
        for slot, cell in enumerate(cells):
            cell.update(recordId=f'{row["id"]}:{cell["cellKey"]}', slot=slot)
        self.cache[key] = cells
        while len(self.cache) > 1000:
            self.cache.popitem(last=False)
        return cells

    def page(self, limit=200, before=None, after=None, row_ids=None):
        self.index.refresh()
        with self.index.lock:
            eligible = [row for row in self.index.rows.values()
                        if (before is None or row['seq'] < before) and (after is None or row['seq'] > after)
                        and (row_ids is None or row['id'] in row_ids)]
            rows = eligible if row_ids is not None else eligible[-limit:] if after is None else eligible[:limit]
            return {'cells': [cell for row in rows for cell in self.cells(row)],
                    'requestNumbers': [self.request_info(row) for row in rows if row.get('type') in ('request','compaction')],
                    'rowIds': [row['id'] for row in rows], 'hasEarlier': len(eligible) > len(rows),
                    'beforeSeq': rows[0]['seq'] if rows else None, 'afterSeq': rows[-1]['seq'] if rows else None}

    def detail(self, row_id, cell_key):
        row = self.index.get_row(row_id)
        key = (row_id, cell_key, row.get('_updated'), self.index.last_seq)
        if key in self.detail_cache:
            self.detail_cache.move_to_end(key)
            return self.detail_cache[key][0]
        data = self.build_detail(row_id, cell_key)
        size = len(json_text(data)) * 4
        if size < 16 * 1024 * 1024:
            self.detail_cache[key] = (data, size)
            self.detail_bytes += size
            while len(self.detail_cache)>20 or self.detail_bytes>32*1024*1024:
                _, (_, removed) = self.detail_cache.popitem(last=False)
                self.detail_bytes -= removed
        return data

    def build_detail(self, row_id, cell_key):
        row = self.index.get_row(row_id)
        template = next((cell for cell in self.cells(row) if cell['cellKey'] == cell_key), None)
        if template is None:
            raise TraceError('没有找到这条轨迹记录。')
        data = {**template, 'detailsPending': False}
        if cell_key == 'prompt':
            data['promptDetail'] = self.prompt(row)
            previous = next((candidate for candidate in reversed(self.requests())
                             if candidate['threadId'] == row['threadId'] and candidate['seq'] < row['seq'] and candidate.get('type') == 'request'), None)
            if previous:
                data['previousPromptDetail'] = self.prompt(previous)
        elif cell_key.startswith('input:'):
            position = int(cell_key.split(':')[1])
            item = self.index.payload(row['_request'])['input'][position]
            blocks = source_blocks(item, row['id'], f'input-{position}')
            data.update(inputDetail='\n\n'.join(b['content'] for b in blocks if b['type'] == 'text'),
                        sourceBlocks=blocks, messageSource={'role': item.get('role'), 'type': item.get('type'),
                                                         **(item.get('internal_chat_message_metadata_passthrough') or {})})
        elif cell_key == 'assistant':
            response = self.index.payload(row.get('_response')) or {}
            blocks = []
            thinking = []
            for item in response.get('output_items', []):
                if item.get('type') == 'message':
                    blocks.extend(source_blocks(item, row['id'], 'output'))
                elif item.get('type') == 'reasoning':
                    thinking.extend(part['text'] for part in item.get('summary', []) if isinstance(part, dict) and isinstance(part.get('text'), str))
                elif item.get('type') in ('function_call', 'custom_tool_call'):
                    blocks.append({'type':'tool-call', 'content': item.get('arguments', item.get('input', '')),
                                   'callId': item.get('call_id'), 'toolName': item.get('name')})
            data.update(outputDetail='\n\n'.join(b['content'] for b in blocks if b['type'] == 'text'),
                        sourceBlocks=blocks, thinkingDetail='\n\n'.join(thinking))
        elif cell_key == 'compaction':
            data['outputDetail'] = json_text(self.index.payload(row.get('_response')))
        else:
            if row.get('type') == 'code':
                data.update(inputDetail=row.get('_code', ''), programSource=row.get('_code', ''))
            else:
                raw = self.index.payload(row.get('_input')) or {}
                payload = raw.get('payload', raw)
                args = payload.get('arguments', payload) if isinstance(payload, dict) else payload
                data['inputDetail'] = args if isinstance(args, str) else json_text(args)
            result = unpack(self.index.payload(row.get('_output')))
            output = result.get('output', result) if isinstance(result, dict) else result
            data['outputDetail'] = output if isinstance(output, str) else json_text(output) if row.get('_output') else ''
            _, _, _, request = self.location(row)
            if request.get('type') == 'request':
                schema = next((tool for tool in self.prompt(request)['tools'] if data.get('toolName') in (tool.get('name'),tool.get('qualifiedName'))), None)
                data['schemaDetail'] = json_text(schema) if schema else ''
            if row.get('type') == 'code':
                # Code cells are captured by the official JavaScript runtime event.
                data['programLanguage'] = 'javascript'
        return data

    def search(self, query, rows):
        terms = query.casefold().split()
        matches = []
        for row_id in rows:
            row = self.index.get_row(row_id)
            for cell in self.cells(row):
                value = self.detail(row_id, cell['cellKey'])
                text = json_text(value).casefold()
                if all(term in text for term in terms):
                    matches.append(cell['recordId'])
        return matches
