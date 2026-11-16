import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'plugins/codex-dsh-trace/server'))
from store import Store, TraceError, CHUNK


class Fixture:
    def __init__(self, root, schema_version=1, started_at=1000):
        self.root = root
        self.schema_version = schema_version
        self.started_at=started_at
        (root/'payloads').mkdir(parents=True)
        (root/'manifest.json').write_text(json.dumps({'schema_version':schema_version,'trace_id':'trace-test',
            'rollout_id':'rollout-test','root_thread_id':'thread-root','started_at_unix_ms':started_at,
            'raw_event_log':'trace.jsonl','payloads_dir':'payloads'}))
        (root/'trace.jsonl').touch()
        self.seq = 0
        self.payloads = 0

    def payload(self, data, kind):
        self.payloads += 1
        name = f'payloads/{self.payloads}.json'
        (self.root/name).write_text(json.dumps(data, ensure_ascii=False))
        return {'raw_payload_id':f'raw_payload:{self.payloads}','kind':{'type':kind},'path':name}

    def event(self, record_type, **values):
        self.seq += 1
        return {'schema_version':self.schema_version,'seq':self.seq,'wall_time_unix_ms':self.started_at+self.seq*10,
                'rollout_id':'rollout-test','thread_id':'thread-root','codex_turn_id':'turn-1',
                'payload':{'type':record_type,**values}}

    def append(self, record_type, **values):
        event = self.event(record_type, **values)
        with (self.root/'trace.jsonl').open('a') as f:
            f.write(json.dumps(event)+'\n')
        return event

    def conversation(self, text='Controlled prompt 🌱'):
        self.append('rollout_started',trace_id='trace-test',root_thread_id='thread-root')
        self.append('thread_started',thread_id='thread-root',agent_path='/root',metadata_payload=None)
        self.append('codex_turn_started',thread_id='thread-root',codex_turn_id='turn-1')
        req=self.payload({'model':'test','input':[{'type':'additional_tools','role':'developer','tools':[]},
            {'type':'message','role':'developer','content':[{'type':'input_text','text':text}]},
            {'type':'message','role':'user','content':[{'type':'input_text','text':'Read fixture'}]}]},'inference_request')
        self.append('inference_started',inference_call_id='first',thread_id='thread-root',codex_turn_id='turn-1',model='test',request_payload=req)
        response=self.payload({'response_id':'resp-first','output_items':[{'type':'custom_tool_call','name':'exec','input':'read()','call_id':'call-1'}],'token_usage':{'input_tokens':10}},'inference_response')
        self.append('inference_completed',inference_call_id='first',response_id='resp-first',response_payload=response)
        self.append('code_cell_started',runtime_cell_id='1',model_visible_call_id='call-1',source_js='read()')
        invocation=self.payload({'tool_name':'exec_command','payload':{'type':'function','arguments':'{"cmd":"cat fixture"}'}},'tool_invocation')
        self.append('tool_call_started',tool_call_id='tool-one',requester={'type':'code_cell','runtime_cell_id':'1'},kind={'type':'exec_command'},summary={'label':'exec_command'},invocation_payload=invocation)
        output=self.payload({'type':'code_mode_response','value':{'output':'fixture value\n','exit_code':0}},'tool_result')
        self.append('tool_call_ended',tool_call_id='tool-one',status='completed',result_payload=output)
        self.append('code_cell_ended',runtime_cell_id='1',status='completed',response_payload=output)
        second=self.payload({'type':'response.create','model':'test','previous_response_id':'resp-first',
            'input':[{'type':'custom_tool_call_output','call_id':'call-1','output':'fixture value\n'}]},'inference_request')
        self.append('inference_started',inference_call_id='second',thread_id='thread-root',codex_turn_id='turn-1',model='test',request_payload=second)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        isolated=patch.dict(os.environ,{'CODEX_ROLLOUT_TRACE_ROOT':str(self.root/'environment-root')})
        isolated.start();self.addCleanup(isolated.stop)
        self.fixture=Fixture(self.root/'bundle')
        self.store=Store(self.root/'config.json')
        self.store.catalog.default_root=self.root/'default'
        self.store.catalog.register(str(self.fixture.root),'Test capture')

    def tearDown(self):
        self.temp.cleanup()

    def test_lazy_index_and_constant_warm_read(self):
        self.fixture.conversation()
        index=self.store.index('trace-test')
        overview=index.overview()
        self.assertEqual(overview['requestCount'],2)
        self.assertEqual(index.metrics['payloadReads'],0)
        before=dict(index.metrics)
        self.assertTrue(index.delta(overview['revision'])['unchanged'])
        index.overview()
        self.assertEqual(index.metrics,before)

    def test_schema_two_live_session_preserves_context_and_auxiliary_events(self):
        self.fixture.schema_version=2
        path=self.fixture.root/'manifest.json';manifest=json.loads(path.read_text());manifest['schema_version']=2;path.write_text(json.dumps(manifest))
        self.fixture.conversation()
        response=self.fixture.payload({'output_items':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':'V2 final reply.'}]}]},'inference_response')
        self.fixture.append('inference_completed',inference_call_id='second',response_id='resp-second',response_payload=response)
        self.fixture.append('history_item_accepted',item_id='recorded-item-1')
        protocol=self.fixture.payload({'type':'task_complete','turn_id':'turn-1','duration_ms':150,'time_to_first_token_ms':30},'protocol_event')
        self.fixture.append('protocol_event_observed',event_type='turn_complete',event_payload=protocol)
        self.fixture.append('codex_turn_ended',codex_turn_id='turn-1',status='completed')
        opened=self.store.open(thread_id='thread-root')
        self.assertEqual(opened['view'],'trace');self.assertEqual(opened['trace']['schemaVersion'],2)
        self.assertEqual(opened['requestCount'],2);self.assertEqual(opened['codeCellCount'],1);self.assertEqual(opened['toolCount'],1)
        self.assertTrue(self.store.details('trace-test','request:second')['context']['complete'])
        self.assertIn('V2 final reply.',self.store.text('trace-test','request:second','response')['text'])

    def test_future_schema_is_reported_instead_of_disappearing_as_missing_recording(self):
        path=self.fixture.root/'manifest.json';manifest=json.loads(path.read_text());manifest['schema_version']=99;path.write_text(json.dumps(manifest))
        listed=self.store.list(True)
        self.assertEqual(listed['traces'],[]);self.assertEqual(listed['unreadableCount'],1)
        self.assertEqual(listed['issues'][0]['threadId'],'thread-root')
        opened=self.store.open(thread_id='thread-root')
        self.assertIn('版本 99',opened['unavailableReason'])
        with self.assertRaisesRegex(TraceError,'版本 99'):self.store.index('trace-test')

    def test_event_schema_must_match_its_manifest(self):
        self.fixture.conversation()
        path=self.fixture.root/'manifest.json';manifest=json.loads(path.read_text());manifest['schema_version']=2;path.write_text(json.dumps(manifest))
        with self.assertRaises(TraceError):self.store.index('trace-test').overview()

    def test_catalog_scans_before_caching_when_monotonic_clock_starts_near_zero(self):
        self.fixture.conversation()
        second=Fixture(self.root/'second-bundle')
        manifest=second.root/'manifest.json';value=json.loads(manifest.read_text())
        value['trace_id']='trace-second';manifest.write_text(json.dumps(value))
        self.store.catalog.register(str(second.root))
        with patch('store.time.monotonic',return_value=0.1):
            self.assertIsNotNone(self.store.catalog.find(trace_id='trace-test'))
            listed=self.store.list()['traces']
        self.assertEqual({item['id'] for item in listed},{'trace-test','trace-second'})

    def test_continuation_keeps_all_prompt_and_output_items(self):
        self.fixture.conversation()
        data=self.store.details('trace-test','request:second')
        self.assertTrue(data['context']['complete'])
        self.assertEqual(len(data['messages']),5)
        self.assertTrue(data['messages'][1]['inherited'])
        text=self.store.text('trace-test','request:second','full_context')['text']
        self.assertIn('Controlled prompt 🌱',text)
        self.assertIn('fixture value',text)
        self.assertEqual(data['context']['previousRequestId'],'request:first')

    def test_missing_previous_response_is_not_claimed_complete(self):
        request=self.fixture.payload({'previous_response_id':'outside','input':[{'type':'message','role':'user','content':[{'type':'input_text','text':'known'}]}]},'inference_request')
        self.fixture.append('inference_started',inference_call_id='only',model='test',request_payload=request)
        data=self.store.details('trace-test','request:only')
        self.assertFalse(data['context']['complete'])
        self.assertEqual(len(data['messages']),1)

    def test_partial_append_and_late_completion_update_existing_row(self):
        self.fixture.conversation()
        index=self.store.index('trace-test')
        old=index.overview()
        payload=self.fixture.payload({'output_items':[],'token_usage':{}},'inference_response')
        line=json.dumps(self.fixture.event('inference_completed',inference_call_id='second',response_id='second-response',response_payload=payload)).encode()
        with (self.fixture.root/'trace.jsonl').open('ab') as f:f.write(line[:30])
        self.assertTrue(index.delta(old['revision'])['unchanged'])
        with (self.fixture.root/'trace.jsonl').open('ab') as f:f.write(line[30:]+b'\n')
        delta=index.delta(old['revision'])
        self.assertEqual(len(delta['rows']),1)
        self.assertEqual(delta['rows'][0]['status'],'complete')
        self.assertEqual(delta['rows'][0]['id'],'request:second')
        self.assertGreater(delta['rows'][0]['version'],old['rows'][-1]['version'])

    def test_live_append_updates_totals_without_reading_payloads(self):
        self.fixture.append('rollout_started',trace_id='trace-test',root_thread_id='thread-root')
        index=self.store.index('trace-test');old=index.overview()
        self.fixture.conversation()
        delta=index.delta(old['revision'])
        self.assertEqual(delta['requestCount'],2)
        self.assertEqual(delta['toolCount'],1)
        self.assertEqual(delta['totalRows'],4)
        self.assertEqual(delta['threads'],[{'id':'thread-root','label':'/root'}])
        self.assertEqual(index.metrics['payloadReads'],0)

    def test_tool_input_output_and_parent_relation(self):
        self.fixture.conversation()
        detail=self.store.details('trace-test','tool:tool-one')
        self.assertEqual(detail['parentId'],'cell:thread-root:1')
        self.assertEqual(detail['exitCode'],0)
        self.assertEqual(detail['nextRequestId'],'request:second')
        self.assertEqual(self.store.text('trace-test','tool:tool-one','arguments')['text'],'{"cmd":"cat fixture"}')
        self.assertEqual(self.store.text('trace-test','tool:tool-one','result')['text'],'fixture value\n')

    def test_unicode_chunking_is_lossless(self):
        expected='🌱汉字\n'*(CHUNK//2)
        self.fixture.conversation(expected)
        chunks=[];offset=0
        while True:
            data=self.store.text('trace-test','request:first','message',1,offset)
            chunks.append(data['text'])
            if data['nextOffset'] is None:break
            offset=data['nextOffset']
        self.assertEqual(''.join(chunks),expected)

    def test_traversal_and_symlink_payloads_are_rejected(self):
        bad={'raw_payload_id':'bad','kind':{'type':'inference_request'},'path':'../private.json'}
        self.fixture.append('inference_started',inference_call_id='bad',model='test',request_payload=bad)
        with self.assertRaises(TraceError):self.store.index('trace-test').overview()
        self.fixture.root.joinpath('trace.jsonl').write_text('');self.fixture.seq=0
        ref=self.fixture.payload({'input':[]},'inference_request')
        path=self.fixture.root/ref['path'];path.unlink();path.symlink_to(self.root/'config.json')
        self.fixture.append('inference_started',inference_call_id='symlink',model='test',request_payload=ref)
        with self.assertRaises(TraceError):self.store.details('trace-test','request:symlink')

    def test_native_open_does_not_substitute_latest_task(self):
        self.fixture.conversation()
        self.assertEqual(self.store.open(thread_id='unrelated-task')['view'],'select')
        self.assertEqual(self.store.open(thread_id='thread-root')['view'],'trace')

    def test_truncation_invalidates_live_revision(self):
        self.fixture.conversation()
        index=self.store.index('trace-test');old=index.overview()['revision']
        (self.fixture.root/'trace.jsonl').write_text('')
        self.assertTrue(index.delta(old)['resync'])
        self.assertEqual(index.overview()['totalRows'],0)

    def test_history_pages_do_not_duplicate_or_read_payloads(self):
        ref=self.fixture.payload({'input':[]},'inference_request')
        for number in range(9):
            self.fixture.append('inference_started',inference_call_id=str(number),model='test',request_payload=ref)
        index=self.store.index('trace-test');page=index.overview(limit=3)
        self.assertTrue(page['hasEarlier']);seen=[r['id'] for r in page['rows']]
        while page['hasEarlier']:
            page=index.overview(limit=3,before=page['beforeSeq'])
            seen=[r['id'] for r in page['rows']]+seen
        self.assertEqual(seen,[f'request:{n}' for n in range(9)])
        self.assertEqual(index.metrics['payloadReads'],0)


if __name__=='__main__':unittest.main()
