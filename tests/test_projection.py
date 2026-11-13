"""Behavior checks for the real Codex → upstream DSH adapter."""
import json
import tempfile
import unittest
from pathlib import Path

from test_store import Fixture
from store import Store, CHUNK, TraceError


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
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

    def test_search_reads_body_beyond_summary_and_schema(self):
        self.fixture.conversation('start '+('x'*5000)+' UNIQUE_DEEP_BODY')
        projector=self.project();page=projector.page()
        self.assertNotIn('UNIQUE_DEEP_BODY',json.dumps(page))
        found=projector.search('unique_deep_body',page['rowIds'])
        self.assertIn('request:first:prompt',found)

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
