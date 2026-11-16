"""Native transcript regression cases use synthetic data only."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'plugins/antigravity-dsh-trace/server'
sys.path.insert(0, str(SERVER))
from native_store import CHUNK, NativeStore, TraceError

spec = importlib.util.spec_from_file_location('antigravity_provider', SERVER / 'main.py')
provider = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provider)

CONVERSATION = '11111111-2222-4333-8444-555555555555'
TRACE = 'native:' + CONVERSATION
FIXTURE = ROOT / 'tests/fixtures/antigravity.jsonl'


class NativeStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.logs = self.root / 'brain' / CONVERSATION / '.system_generated' / 'logs'
        self.logs.mkdir(parents=True)
        self.path = self.logs / 'transcript_full.jsonl'
        self.path.write_bytes(FIXTURE.read_bytes())
        self.store = NativeStore(self.root)

    def append(self, event):
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + '\n')

    def test_native_messages_tools_and_exact_conversation_binding(self):
        opened = self.store.open(thread_id=CONVERSATION)
        self.assertEqual(opened['trace']['source'], 'antigravity-transcript')
        self.assertEqual(opened['trace']['id'], TRACE)
        self.assertEqual(opened['toolCount'], 3)
        self.assertFalse(opened['trace']['capabilities']['rawModelRequest'])
        self.assertEqual(self.store.open(thread_id='unrelated-conversation')['view'], 'select')
        self.assertIsNone(self.store.open()['currentThreadId'])
        page = self.store.projection(TRACE)
        self.assertEqual([cell['turn'] for cell in page['cells'] if cell['kind'] == 'user'], [1, 2])
        tools = [cell for cell in page['cells'] if cell['kind'] == 'tool']
        self.assertEqual([cell['toolName'] for cell in tools], ['read_file', 'run_command', 'read_file'])
        self.assertIn('native output', tools[0]['result'])
        self.assertIn('synthetic-check', tools[1]['result'])
        self.assertTrue(tools[-1]['isError'])
        self.assertEqual(opened['status'], 'error')

    def test_no_fabricated_requests_context_schemas_or_durations(self):
        detail = self.store.details(TRACE, 'step:1')
        self.assertFalse(detail['context']['available'])
        self.assertEqual(detail['messages'], [])
        for section in ('full_context', 'raw_request', 'tools'):
            value = self.store.text(TRACE, 'step:1', section)
            self.assertFalse(value['available'])
            self.assertTrue(value['reasonEn'])
        native = json.loads(self.store.text(TRACE, 'step:1', 'response')['text'])
        self.assertEqual(native['type'], 'PLANNER_RESPONSE')
        page = self.store.projection(TRACE)
        self.assertTrue(all(cell['timeSeconds'] is None for cell in page['cells']))
        self.assertTrue(all(request['completedAt'] is None for request in page['requestNumbers']))
        self.assertTrue(all('requestConfig' not in request for request in page['requestNumbers']))
        for cell in page['cells']:
            if 'assistantMetrics' in cell:
                self.assertFalse(cell['assistantMetrics']['timingRecorded'])
                self.assertNotIn('input', cell)
                self.assertNotIn('cacheRead', cell)

    def test_hydration_text_chunks_unicode_and_search_match_contract(self):
        long_text = '合成🌱' * (CHUNK // 3 + 100)
        self.append({'step_index': 9, 'source': 'model', 'type': 'PLANNER_RESPONSE', 'status': 'DONE',
                     'created_at': '2026-11-16T06:01:10Z', 'content': long_text})
        detail = self.store.cell_detail(TRACE, 'step:9', 'assistant')
        self.assertIn('fields', detail)
        self.assertEqual(detail['fields']['outputDetail']['totalChars'], len(long_text))
        first = self.store.cell_text(TRACE, 'step:9', 'assistant', 'outputDetail', version=detail['cell']['version'])
        second = self.store.cell_text(TRACE, 'step:9', 'assistant', 'outputDetail', first['nextOffset'], detail['cell']['version'])
        self.assertEqual(first['text'] + second['text'], long_text)
        matches = self.store.search(TRACE, 'native output', ['tool:1:0'])
        self.assertEqual(matches['matches'], ['tool:1:0:tool'])
        found = self.store.record(TRACE, call_id=f'native-call:{CONVERSATION}:1:0')['row']
        self.assertEqual(found['id'], 'tool:1:0')

    def test_live_append_partial_tail_and_late_result_updates_existing_tool(self):
        old = self.store.index(TRACE).overview()
        self.append({'step_index': 9, 'type': 'USER_INPUT', 'status': 'DONE', 'content': 'Synthetic live turn'})
        self.append({'step_index': 10, 'type': 'PLANNER_RESPONSE', 'status': 'DONE', 'content': '',
                     'tool_calls': [{'name': 'read_file', 'args': {'Path': '/synthetic/live'}}]})
        index = self.store.index(TRACE)
        mid = index.overview()
        cell = self.store.cell_detail(TRACE, 'tool:10:0', 'tool')
        self.assertEqual(index.rows['tool:10:0']['status'], 'running')
        payload = json.dumps({'step_index': 11, 'type': 'GENERIC', 'status': 'DONE', 'content': 'Synthetic live completion'}).encode()
        with self.path.open('ab') as stream:
            stream.write(payload[:25])
        self.assertTrue(index.delta(mid['revision'])['unchanged'])
        with self.path.open('ab') as stream:
            stream.write(payload[25:] + b'\n')
        delta = index.delta(mid['revision'])
        self.assertEqual([row['id'] for row in delta['rows']], ['tool:10:0'])
        self.assertEqual(delta['rows'][0]['status'], 'complete')
        self.assertEqual(index.delta(old['revision'])['toolCount'], 4)
        with self.assertRaisesRegex(TraceError, '记录已更新'):
            self.store.cell_text(TRACE, 'tool:10:0', 'tool', 'outputDetail', version=cell['cell']['version'])

    def test_duplicate_steps_use_latest_value_and_reset_resyncs_removed_rows(self):
        before = self.store.index(TRACE).overview()
        self.append({'step_index': 4, 'type': 'PLANNER_RESPONSE', 'status': 'DONE', 'content': 'Synthetic revised reply'})
        delta = self.store.index(TRACE).delta(before['revision'])
        self.assertEqual([row['id'] for row in delta['rows']], ['step:4'])
        self.path.write_text(json.dumps({'step_index': 0, 'type': 'USER_INPUT', 'status': 'DONE', 'content': 'Synthetic reset'}) + '\n')
        self.assertTrue(self.store.index(TRACE).delta(delta['revision'])['resync'])

    def test_compact_fallback_is_explicit_and_full_source_wins(self):
        compact = self.logs / 'transcript.jsonl'
        self.path.rename(compact)
        first = self.store.open(thread_id=CONVERSATION)
        self.assertTrue(first['compactFallback'])
        self.assertEqual(first['sourceFile'], 'transcript.jsonl')
        self.path.write_bytes(FIXTURE.read_bytes())
        second = self.store.open(thread_id=CONVERSATION)
        self.assertFalse(second['compactFallback'])
        self.assertTrue(self.store.index(TRACE).delta(first['revision'])['resync'])

    def test_unknown_native_step_and_mismatched_result_are_preserved_not_mispaired(self):
        self.append({'step_index': 9, 'type': 'PLANNER_RESPONSE', 'status': 'DONE', 'content': '',
                     'tool_calls': [{'name': 'read_file', 'args': {}}]})
        self.append({'step_index': 10, 'type': 'GENERIC', 'status': 'DONE', 'tool_name': 'other_tool', 'content': 'Unmatched synthetic output'})
        self.append({'step_index': 11, 'type': 'FUTURE_NATIVE_EVENT', 'status': 'DONE', 'content': 'Future synthetic event'})
        index = self.store.index(TRACE)
        self.assertIsNone(index.rows['tool:9:0']['_result'])
        self.assertIn('step:10', index.rows)
        self.assertIn('step:11', index.rows)

    def test_cancelled_native_planner_and_tool_preserve_interruption_markers(self):
        self.append({'step_index': 9, 'type': 'PLANNER_RESPONSE', 'status': 'CANCELLED', 'content': 'Synthetic cancelled response'})
        self.append({'step_index': 10, 'type': 'PLANNER_RESPONSE', 'status': 'DONE', 'content': '',
                     'tool_calls': [{'name': 'read_file', 'args': {}}]})
        self.append({'step_index': 11, 'type': 'GENERIC', 'status': 'CANCELED', 'content': 'Synthetic cancelled tool'})
        page = self.store.projection(TRACE)
        cells = {cell['rowId']: cell for cell in page['cells']}
        self.assertTrue(cells['step:9']['isError'])
        self.assertTrue(cells['tool:10:0']['isError'])
        self.assertEqual(self.store.request_info(TRACE, 'step:9')['request']['status'], 'error')

    def test_provider_restart_and_repeated_source_switches_invalidate_old_revisions(self):
        initial = self.store.index(TRACE).overview()['revision']
        self.assertTrue(NativeStore(self.root).index(TRACE).delta(initial)['resync'])
        compact = self.logs / 'transcript.jsonl'
        for _ in range(2):
            self.path.rename(compact)
            compact_revision = self.store.index(TRACE).overview()['revision']
            self.path.write_bytes(FIXTURE.read_bytes())
            self.assertTrue(self.store.index(TRACE).delta(compact_revision)['resync'])
            compact.unlink()

    def test_path_validation_symlinks_and_malformed_complete_lines(self):
        for conv in ('../outside', '/absolute', 'x/y', 'x.y'):
            with self.assertRaises(TraceError):
                self.store.open(thread_id=conv)
        self.path.unlink()
        self.path.symlink_to(FIXTURE)
        with self.assertRaises(TraceError):
            self.store.open(thread_id=CONVERSATION)
        self.path.unlink()
        self.path.write_text('{broken}\n')
        with self.assertRaisesRegex(TraceError, '第 1 行'):
            self.store.open(thread_id=CONVERSATION)

    def test_provider_host_metadata_required_and_tool_schemas_validate(self):
        saved = provider.STORE
        provider.STORE = self.store
        self.addCleanup(setattr, provider, 'STORE', saved)
        self.assertEqual(len(provider.TOOLS), 15)
        self.assertEqual(provider.call('open_rollout_viewer', {}, {'threadId': CONVERSATION})['view'], 'select')
        opened = provider.call('open_rollout_viewer', {}, {'host': 'antigravity', 'conversationId': CONVERSATION})
        self.assertEqual(opened['currentThreadId'], CONVERSATION)
        for args in ({'traceId': TRACE, 'limit': True}, {'traceId': TRACE, 'limit': 501}, {'traceId': TRACE, 'extra': 1}):
            with self.assertRaises(TraceError):
                provider.call('get_rollout_overview', args)
        with self.assertRaises(TraceError):
            provider.call('add_rollout_directory', {'path': str(self.root)})

    def test_stdio_readonly_protocol_opens_synthetic_native_conversation(self):
        requests = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
                    {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'open_rollout_viewer', 'arguments': {},
                     '_meta': {'host': 'antigravity', 'conversationId': CONVERSATION}}}]
        result = subprocess.run([sys.executable, str(SERVER / 'main.py'), '--data-root', str(self.root)],
                                input=''.join(json.dumps(request) + '\n' for request in requests), text=True,
                                capture_output=True, check=True, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        responses = {value['id']: value for value in map(json.loads, result.stdout.splitlines())}
        self.assertEqual(responses[1]['result']['serverInfo']['name'], 'antigravity-dsh-trace')
        data = responses[2]['result']['structuredContent']
        self.assertEqual(data['trace']['id'], TRACE)
        self.assertEqual(data['toolCount'], 3)


if __name__ == '__main__':
    unittest.main()
