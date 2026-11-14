"""Behavior checks for the real Codex → upstream DSH adapter."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from test_store import Fixture
from store import Store, CHUNK, TraceError


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        isolated=patch.dict(os.environ,{'CODEX_ROLLOUT_TRACE_ROOT':str(self.root/'environment-root')})
        isolated.start();self.addCleanup(isolated.stop)
        self.fixture = Fixture(self.root/'bundle')
        self.store = Store(self.root/'config.json')
        self.store.catalog.default_root = self.root/'unused'
        self.store.catalog.register(str(self.fixture.root))

    def tearDown(self):
        self.temp.cleanup()

    def project(self):
        return self.store.projection('trace-test')

    def test_turns_steps_and_request_result_anchor(self):
        self.fixture.conversation()
        page = self.project().page()
        self.assertEqual([cell['kind'] for cell in page['cells']],
                         ['system','user','message','tool','subtool','message'])
        self.assertEqual([request['step'] for request in page['requestNumbers']], [1,2])
        first = page['requestNumbers'][0]
        matches = [cell for cell in page['cells'] if cell.get('sourceSeq') == first['resultSeq']]
        self.assertEqual([cell['kind'] for cell in matches], ['message'])
        self.assertTrue(all(cell['detailsPending'] for cell in page['cells']))
        self.assertEqual(self.project().index.overview()['codeCellCount'],1)
        self.assertNotIn('Controlled prompt', json.dumps(page))

    def test_prompt_hydration_uses_lossless_unicode_chunks(self):
        expected='🌱完整上下文\n'*12000
        self.fixture.conversation(expected)
        projector=self.project();projector.page()
        meta=self.store.cell_detail('trace-test','request:first','prompt')
        reads=projector.index.metrics['payloadReads']
        self.assertGreater(meta['fields']['promptDetail']['totalChars'],CHUNK)
        offset=0;chunks=[]
        while offset is not None:
            part=self.store.cell_text('trace-test','request:first','prompt','promptDetail',offset)
            chunks.append(part['text']);offset=part['nextOffset']
        prompt=json.loads(''.join(chunks))
        self.assertIn(expected,prompt['system'])
        self.assertEqual(projector.index.metrics['payloadReads'],reads)

    def test_tool_parent_references_are_available_without_assistant_hydration(self):
        self.fixture.conversation()
        page=self.project().page()
        assistant=next(cell for cell in page['cells'] if cell['recordId']=='request:first:assistant')
        calls=[block for block in assistant['sourceBlocks'] if block['type']=='tool-call']
        self.assertEqual([block['callId'] for block in calls],['call-1'])
        self.assertTrue(assistant['detailsPending'])
        self.assertTrue(all(block['content']=='' for block in calls))
        self.assertNotIn('read()',json.dumps(assistant))

    def test_call_lookup_uses_recorded_identity_without_reading_bodies(self):
        self.fixture.conversation()
        index=self.store.index('trace-test');index.overview();reads=index.metrics['payloadReads']
        self.assertEqual(self.store.locate_call('trace-test','call-1')['id'],'cell:thread-root:1')
        self.assertEqual(self.store.locate_call('trace-test','cell:thread-root:1')['callId'],'call-1')
        self.assertEqual(self.store.locate_call('trace-test','tool-one')['id'],'tool:tool-one')
        self.assertEqual(index.metrics['payloadReads'],reads)
        with self.assertRaises(TraceError):self.store.locate_call('trace-test','missing-call')

    def test_call_launcher_returns_only_metadata_and_locator_rejects_ambiguous_arguments(self):
        import main
        self.fixture.conversation()
        with patch.object(main,'STORE',self.store):
            launched=main.call('show_rollout_trace',{'traceId':'trace-test','callId':'call-1'})
            self.assertEqual(set(launched),{'view','trace','focusCallId'})
            self.assertEqual(launched['focusCallId'],'call-1')
            self.assertEqual(main.call('get_rollout_record',{'traceId':'trace-test','callId':'call-1'})['row']['id'],'cell:thread-root:1')
            with self.assertRaises(TraceError):main.call('get_rollout_record',{'traceId':'trace-test'})
            with self.assertRaises(TraceError):main.call('get_rollout_record',{'traceId':'trace-test','rowId':'tool:tool-one','callId':'call-1'})

    def test_token_buckets_and_cumulative_usage_do_not_double_count_cache(self):
        self.fixture.conversation()
        row=self.project().index.get_row('request:first')
        ref=self.fixture.payload({'output_items':[], 'token_usage':{'input_tokens':100,'cached_input_tokens':30,
            'cache_write_input_tokens':10,'output_tokens':20,'reasoning_output_tokens':5}},'inference_response')
        self.fixture.append('inference_completed',inference_call_id='first',response_id='resp-first',response_payload=ref)
        projector=self.project();row=projector.index.get_row('request:first')
        info=projector.request_info(row,True)
        self.assertEqual(info['usage'],{'input':60,'cacheRead':30,'cacheWrite':10,'output':20,'reasoning':5})
        self.assertEqual(info['usage'],info['cumulativeUsage'])

    def test_program_source_and_tool_arguments_are_not_reformatted(self):
        self.fixture.conversation()
        projector=self.project()
        code=projector.detail('cell:thread-root:1','tool')
        self.assertEqual(code['programSource'],'read()')
        self.assertEqual(code['programLanguage'],'javascript')
        tool=projector.detail('tool:tool-one','tool')
        self.assertEqual(tool['inputDetail'],'{"cmd":"cat fixture"}')
        self.assertEqual(tool['outputDetail'],'fixture value\n')

    def test_code_summary_is_available_before_opening_its_details(self):
        self.fixture.conversation()
        original='{ "code": "console.log(42);\\n", "description": "Describe the program" }'
        ref=self.fixture.payload({'tool_name':'run_code','payload':{'arguments':original}},'tool_invocation')
        self.fixture.append('tool_call_started',tool_call_id='native-program',requester={'type':'model'},
                            kind={'type':'other','name':'run_code'},summary={'label':'run_code'},invocation_payload=ref)
        projector=self.project();cell=projector.page()['cells'][-1]
        self.assertEqual(cell['programDescription'],'Describe the program')
        detail=projector.detail('tool:native-program','tool')
        self.assertNotIn('programSource',detail)
        self.assertEqual(detail['inputDetail'],original)

    def test_namespaced_tool_schemas_keep_their_identity(self):
        tools=[{'type':'namespace','name':namespace,'tools':[{'type':'function','name':'echo',
            'description':namespace,'parameters':{'type':'object'}}]} for namespace in ('first','second')]
        request=self.fixture.payload({'input':[],'tools':tools},'inference_request')
        self.fixture.append('inference_started',inference_call_id='namespaces',model='test',request_payload=request)
        invocation=self.fixture.payload({'tool_namespace':'second','tool_name':'echo','payload':{'arguments':'{}'}},'tool_invocation')
        self.fixture.append('tool_call_started',tool_call_id='echo',requester={'type':'model'},
                            kind={'type':'other','name':'echo'},summary={'label':'echo'},invocation_payload=invocation)
        projector=self.project();projector.page()
        tools=projector.prompt(projector.requests()[0])['tools']
        self.assertEqual([tool['name'] for tool in tools],['first.echo','second.echo'])
        schema=json.loads(projector.detail('tool:echo','tool')['schemaDetail'])
        self.assertEqual(schema['description'],'second')

    def test_latest_in_history_tool_declaration_replaces_its_old_schema(self):
        self.fixture.conversation()
        def declaration(description):return {'type':'additional_tools','role':'developer','tools':[{'type':'namespace','name':'service','tools':[{'type':'function','name':'echo','description':description,'parameters':{'type':'object'}}]}]}
        first=self.fixture.root/'payloads/1.json';value=json.loads(first.read_text());value['input'][0]=declaration('old schema');first.write_text(json.dumps(value))
        second=self.fixture.root/'payloads/5.json';value=json.loads(second.read_text());value['input'].append(declaration('new schema'));second.write_text(json.dumps(value))
        projector=self.project();projector.page()
        tools=projector.prompt(projector.requests()[-1])['tools']
        self.assertEqual(len(tools),1)
        self.assertEqual(tools[0]['name'],'service.echo')
        self.assertEqual(tools[0]['description'],'new schema')

    def test_request_numbers_and_steps_survive_cross_agent_append(self):
        request=self.fixture.payload({'input':[]},'inference_request')
        for thread,turn,name in [('thread-root','root-turn','root-first'),('thread-child','child-turn','child-first')]:
            self.fixture.append('codex_turn_started',thread_id=thread,codex_turn_id=turn)
            self.fixture.append('inference_started',inference_call_id=name,thread_id=thread,codex_turn_id=turn,model='test',request_payload=request)
        projector=self.project();before=projector.page()
        self.assertEqual([q['step'] for q in before['requestNumbers']],[1,1])
        self.fixture.append('inference_started',inference_call_id='root-second',thread_id='thread-root',codex_turn_id='root-turn',model='test',request_payload=request)
        after=projector.page()
        self.assertEqual([q['number'] for q in after['requestNumbers']],[1,2,3])
        self.assertEqual([q['step'] for q in after['requestNumbers']],[1,1,2])
        self.assertEqual([q['turn'] for q in after['requestNumbers']],[1,2,1])

    def test_search_reads_body_beyond_summary_and_schema(self):
        self.fixture.conversation('start '+('x'*5000)+' UNIQUE_DEEP_BODY')
        projector=self.project();page=projector.page()
        self.assertNotIn('UNIQUE_DEEP_BODY',json.dumps(page))
        found=projector.search('unique_deep_body',page['rowIds'])
        self.assertIn('request:first:prompt',found)

    def test_search_includes_the_displayed_locale_group_labels(self):
        self.fixture.conversation();projector=self.project();page=projector.page()
        expected={cell['recordId'] for cell in page['cells'] if not cell.get('requestOnly')}
        self.assertEqual(projector.search('step',page['rowIds']),[])
        self.assertEqual(set(projector.search('step',page['rowIds'],'en')),expected)
        self.assertEqual(set(projector.search('ステップ',page['rowIds'],'ja')),expected)

    def test_search_excludes_hidden_row_flags_but_keeps_actual_boolean_values(self):
        self.fixture.conversation();projector=self.project();page=projector.page()
        self.assertEqual(projector.search('false',page['rowIds']),[])
        result=self.fixture.payload({'value':False,'label':'actual boolean'},'tool_result')
        self.fixture.append('tool_call_ended',tool_call_id='tool-one',status='completed',result_payload=result)
        projector=self.project();page=projector.page()
        self.assertEqual(projector.search('false',page['rowIds']),['tool:tool-one:tool'])

    def test_empty_failed_request_has_no_fabricated_assistant_result_link(self):
        self.fixture.conversation()
        self.fixture.append('inference_failed',inference_call_id='second',error='Controlled empty failure',partial_response_payload=None)
        page=self.project().page()
        self.assertNotIn('resultSeq',page['requestNumbers'][-1])
        self.assertTrue(page['cells'][-1]['requestOnly'])
        self.assertEqual(page['requestNumbers'][-1]['error'],'Controlled empty failure')

    def test_reasoning_only_is_not_mislabelled_as_a_tool_call(self):
        self.fixture.conversation()
        response=self.fixture.payload({'output_items':[{'type':'reasoning','summary':[{'type':'summary_text','text':'Public summary'}]}]},'inference_response')
        self.fixture.append('inference_completed',inference_call_id='second',response_id='r-two',response_payload=response)
        projector=self.project();page=projector.page()
        self.assertEqual(page['cells'][-1]['text'],'')
        self.assertEqual(page['cells'][-1]['previewMarkdown'],'Public summary')
        self.assertEqual(projector.detail('request:second','assistant')['thinkingDetail'],'Public summary')
        opaque=self.fixture.payload({'output_items':[{'type':'reasoning','summary':None,'encrypted_content':'opaque'}]},'inference_response')
        self.fixture.append('inference_completed',inference_call_id='second',response_id='r-two',response_payload=opaque)
        page=self.project().page()
        self.assertNotIn('resultSeq',page['requestNumbers'][-1])
        self.assertNotIn('仅工具调用',page['cells'][-1]['text'])

    def test_assistant_image_only_has_a_bounded_caption_and_full_image_detail(self):
        self.fixture.conversation()
        image='data:image/png;base64,aGVsbG8='
        response=self.fixture.payload({'output_items':[{'type':'message','role':'assistant','content':[{'type':'input_image','image_url':image}]}]},'inference_response')
        self.fixture.append('inference_completed',inference_call_id='second',response_id='r-two',response_payload=response)
        projector=self.project();page=projector.page()
        self.assertEqual(page['cells'][-1]['text'],'图片 ×1')
        self.assertNotIn(image,json.dumps(page))
        detail=projector.detail('request:second','assistant')
        self.assertEqual(detail['sourceBlocks'][0]['attachment']['recordedUrl'],image)

    def test_completed_record_refreshes_existing_metadata_and_detail(self):
        self.fixture.conversation()
        projector=self.project();before=projector.page()
        self.assertIsNone(before['cells'][-1]['timeSeconds'])
        response=self.fixture.payload({'output_items':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':'new final value'}]}]},'inference_response')
        self.fixture.append('inference_completed',inference_call_id='second',response_id='resp-two',response_payload=response)
        after=self.store.projection('trace-test').page(row_ids=['request:second'])
        self.assertEqual(after['cells'][0]['previewMarkdown'],'new final value')
        self.assertIsNotNone(after['cells'][0]['timeSeconds'])
        self.assertEqual(projector.detail('request:second','assistant')['outputDetail'],'new final value')

    def test_images_files_and_original_block_order(self):
        image='data:image/png;base64,aGVsbG8='
        request=self.fixture.payload({'input':[{'type':'message','role':'user','content':[
            {'type':'input_text','text':'before'}, {'type':'input_image','image_url':image,'width':10,'height':20},
            {'type':'input_file','filename':'empty.txt','size':0,'mime_type':'text/plain'},
            {'type':'input_text','text':'after'}]}]},'inference_request')
        self.fixture.append('inference_started',inference_call_id='attachments',model='test',request_payload=request)
        projector=self.project();page=projector.page()
        self.assertNotIn(image,json.dumps(page))
        cell=projector.detail('request:attachments','input:0')
        self.assertEqual(cell['inputDetail'],'before\n\nafter')
        self.assertEqual([block['type'] for block in cell['sourceBlocks']],['text','image','file','text'])
        self.assertEqual(cell['sourceBlocks'][1]['attachment']['recordedUrl'],image)
        self.assertEqual(cell['sourceBlocks'][2]['file']['bytes'],0)

    def test_request_pages_and_direct_missing_record(self):
        self.fixture.conversation();projector=self.project()
        page=projector.page(limit=2)
        self.assertTrue(page['hasEarlier'])
        earlier=projector.page(limit=2,before=page['beforeSeq'])
        self.assertFalse(set(page['rowIds'])&set(earlier['rowIds']))
        with self.assertRaises(TraceError):projector.detail('request:first','not-a-cell')

    def test_native_root_chooses_newest_recording_after_resume(self):
        self.fixture.conversation()
        self.assertEqual(self.store.open(thread_id='thread-root')['trace']['id'],'trace-test')
        later=Fixture(self.root/'later')
        path=later.root/'manifest.json';meta=json.loads(path.read_text())
        meta.update(trace_id='trace-later',started_at_unix_ms=2000);path.write_text(json.dumps(meta))
        self.store.catalog.register(str(later.root))
        self.assertEqual(self.store.open(thread_id='thread-root')['trace']['id'],'trace-test')
        self.assertEqual(self.store.open(trace_id='trace-later')['rows'],[])
        later.conversation()
        self.assertEqual(self.store.open(thread_id='thread-root')['trace']['id'],'trace-later')
        self.assertEqual(self.store.open(thread_id='unrelated-root')['view'],'select')

    def test_live_binding_uses_exact_root_and_returns_only_metadata(self):
        self.fixture.conversation()
        resolved=self.store.binding('thread-root')
        self.assertEqual(set(resolved),{'currentThreadId','trace'})
        self.assertEqual(resolved['trace']['id'],'trace-test')
        self.assertNotIn('_path',resolved['trace'])
        self.assertEqual(self.store.index('trace-test').metrics['payloadReads'],0)
        self.assertIsNone(self.store.binding('unrelated-root')['trace'])

    def test_restarted_empty_recording_preserves_history_until_first_new_request(self):
        self.fixture.conversation()
        later=Fixture(self.root/'resumed')
        manifest=later.root/'manifest.json';meta=json.loads(manifest.read_text())
        meta.update(trace_id='trace-resumed',started_at_unix_ms=3000);manifest.write_text(json.dumps(meta))
        self.store.catalog.register(str(later.root))
        later.append('rollout_started',trace_id='trace-resumed',root_thread_id='thread-root')
        later.append('thread_started',thread_id='thread-root',agent_path='/root')
        self.assertEqual(self.store.binding('thread-root')['trace']['id'],'trace-test')
        request=later.payload({'input':[{'type':'message','role':'user','content':[{'type':'input_text','text':'New turn after resume'}]}]},'inference_request')
        later.append('inference_started',inference_call_id='resumed-first',thread_id='thread-root',request_payload=request)
        self.assertEqual(self.store.binding('thread-root')['trace']['id'],'trace-resumed')
        self.assertEqual(self.store.open(thread_id='thread-root')['requestCount'],1)

    def test_explicit_trace_cannot_silently_bind_a_different_root(self):
        self.fixture.conversation()
        with self.assertRaisesRegex(TraceError,'录制与聊天标识不一致'):
            self.store.open(trace_id='trace-test',thread_id='unrelated-root')

    def test_compaction_is_grouped_between_turns_with_recorded_model(self):
        request=self.fixture.payload({'input':[],'model':'compact-model'},'compaction_request')
        self.fixture.append('compaction_request_started',compaction_id='compact',compaction_request_id='attempt',
                            thread_id='thread-root',codex_turn_id=None,model='compact-model',provider_name='recorded-provider',request_payload=request)
        result=self.fixture.payload({'output_items':[{'type':'compaction','encrypted_content':'opaque'}]},'compaction_response')
        self.fixture.append('compaction_request_completed',compaction_id='compact',compaction_request_id='attempt',response_payload=result)
        page=self.project().page()
        self.assertIsNone(page['cells'][0]['turn'])
        self.assertEqual(page['cells'][0]['kind'],'compacted')
        self.assertEqual(page['requestNumbers'][0]['purpose'],'compaction')
        self.assertEqual(page['requestNumbers'][0]['provider'],'recorded-provider')
        self.assertEqual(self.project().index.overview()['requestCount'],1)

    def test_failed_and_cancelled_partial_outputs_remain_inspectable(self):
        self.fixture.conversation()
        partial=self.fixture.payload({'output_items':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':'partial output'}]}]},'inference_response')
        self.fixture.append('inference_cancelled',inference_call_id='second',reason='user cancelled',partial_response_payload=partial)
        projector=self.project();page=projector.page()
        self.assertTrue(page['cells'][-1]['isError'])
        self.assertEqual(projector.detail('request:second','assistant')['outputDetail'],'partial output')
        self.assertEqual(page['requestNumbers'][-1]['error'],'user cancelled')

    def test_json_null_result_is_available_and_not_missing(self):
        self.fixture.conversation()
        result=self.fixture.payload(None,'tool_result')
        self.fixture.append('tool_call_ended',tool_call_id='tool-one',status='completed',result_payload=result)
        value=self.store.text('trace-test','tool:tool-one','raw_result')
        self.assertTrue(value['available']);self.assertEqual(value['text'],'null')

    def test_business_value_field_is_not_a_result_envelope(self):
        self.fixture.conversation()
        expected={'value':42,'label':'retain this field'}
        result=self.fixture.payload(expected,'tool_result')
        self.fixture.append('tool_call_ended',tool_call_id='tool-one',status='completed',result_payload=result)
        self.assertEqual(json.loads(self.store.text('trace-test','tool:tool-one','result')['text']),expected)
        self.assertEqual(json.loads(self.project().detail('tool:tool-one','tool')['outputDetail']),expected)

    def test_tool_images_and_error_text_keep_their_recorded_order(self):
        self.fixture.conversation()
        image='data:image/png;base64,aGVsbG8='
        raw={'isError':True,'content':[{'type':'text','text':' \n'},
             {'type':'image','mimeType':'image/png','data':'aGVsbG8='}]}
        result=self.fixture.payload(raw,'tool_result')
        self.fixture.append('tool_call_ended',tool_call_id='tool-one',status='completed',result_payload=result)
        projector=self.project();page=projector.page()
        self.assertNotIn(image,json.dumps(page))
        cell=projector.detail('tool:tool-one','tool')
        self.assertTrue(cell['isError']);self.assertEqual(cell['outputDetail'],' \n')
        self.assertEqual([block['type'] for block in cell['outputBlocks']],['text','image'])
        self.assertEqual(cell['outputBlocks'][1]['attachment']['recordedUrl'],image)

    def test_code_cell_text_and_images_use_the_recorded_content_items(self):
        self.fixture.conversation()
        raw={'response':{'Result':{'cell_id':'1','content_items':[{'type':'input_text','text':'console line\n'},
             {'type':'input_image','image_url':'data:image/png;base64,aGVsbG8='}],'error_text':None}}}
        result=self.fixture.payload(raw,'tool_result')
        self.fixture.append('code_cell_ended',runtime_cell_id='1',status='completed',response_payload=result)
        cell=self.project().detail('cell:thread-root:1','tool')
        self.assertEqual(cell['outputDetail'],'console line\n')
        self.assertEqual([block['type'] for block in cell['outputBlocks']],['text','image'])

    def test_large_structured_result_only_sends_a_bounded_ledger_preview(self):
        self.fixture.conversation()
        result=self.fixture.payload({'value':'x'*1000000,'label':'complete JSON stays in details'},'tool_result')
        self.fixture.append('tool_call_ended',tool_call_id='tool-one',status='completed',result_payload=result)
        page=self.project().page();self.assertLess(len(json.dumps(page)),20000)
        detail=self.project().detail('tool:tool-one','tool')
        self.assertEqual(len(json.loads(detail['outputDetail'])['value']),1000000)

    def test_paging_never_combines_different_live_versions(self):
        self.fixture.conversation()
        metadata=self.store.cell_detail('trace-test','request:second','assistant')
        old_version=metadata['cell']['version']
        partial=self.fixture.payload({'output_items':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':'changed during read'}]}]},'inference_response')
        self.fixture.append('inference_completed',inference_call_id='second',response_id='response-two',response_payload=partial)
        with self.assertRaisesRegex(TraceError,'记录已更新'):
            self.store.cell_text('trace-test','request:second','assistant','outputDetail',0,old_version)

    def test_long_response_chain_is_iterative_and_preserves_every_item(self):
        previous=None
        for number in range(1100):
            raw={'input':[{'type':'message','role':'user','content':[{'type':'input_text','text':str(number)}]}]}
            if previous:raw['previous_response_id']=previous
            request=self.fixture.payload(raw,'inference_request')
            self.fixture.append('inference_started',inference_call_id=str(number),model='test',request_payload=request)
            previous=f'response-{number}'
            response=self.fixture.payload({'output_items':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':f'answer-{number}'}]}]},'inference_response')
            self.fixture.append('inference_completed',inference_call_id=str(number),response_id=previous,response_payload=response)
        context=self.store.index('trace-test').context('request:1099')
        self.assertTrue(context['complete']);self.assertEqual(len(context['items']),2199)
        self.assertEqual(context['items'][0]['value']['content'][0]['text'],'0')
        self.assertEqual(context['items'][-1]['value']['content'][0]['text'],'1099')


if __name__=='__main__':unittest.main()
