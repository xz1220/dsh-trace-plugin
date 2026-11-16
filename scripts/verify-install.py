"""Read-only smoke test of an installed plugin against a real recorded task."""
import argparse
import hashlib
import json
import select
import subprocess
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--plugin-dir',type=Path,required=True)
parser.add_argument('--trace-id',required=True)
parser.add_argument('--expect-text',action='append',default=[])
parser.add_argument('--out',type=Path)
args=parser.parse_args()
root=args.plugin_dir.resolve()
process=subprocess.Popen(['python3',str(root/'server/main.py')],cwd=root,stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
counter=0

def rpc(method,params):
    global counter
    counter+=1
    process.stdin.write(json.dumps({'jsonrpc':'2.0','id':counter,'method':method,'params':params})+'\n')
    process.stdin.flush()
    assert select.select([process.stdout],[],[],10)[0],'MCP timed out'
    value=json.loads(process.stdout.readline())
    assert value.get('id')==counter and 'error' not in value,'MCP request failed'
    return value['result']

def call(name,arguments):
    result=rpc('tools/call',{'name':name,'arguments':arguments})
    assert not result.get('isError'),'Tool failed'
    return result['structuredContent']

try:
    version=rpc('initialize',{'protocolVersion':'2025-11-25','clientInfo':{'name':'install-check','version':'1'},'capabilities':{}})['serverInfo']['version']
    tools=rpc('tools/list',{})['tools']
    entry=next(t for t in tools if t['name']=='open_rollout_viewer')
    assert entry['_meta']['openai/ui']['entrypoints']==[{'type':'thread'}]
    a={'traceId':args.trace_id}
    launch=call('show_rollout_trace',a)
    assert launch['view']=='open' and 'rows' not in launch
    data=call('get_rollout_overview',a)
    bound=rpc('tools/call',{'name':'open_rollout_viewer','arguments':{},'_meta':{'threadId':data['trace']['threadId']}})['structuredContent']
    assert bound['view']=='trace' and bound['trace']['threadId']==data['trace']['threadId']
    missing=rpc('tools/call',{'name':'open_rollout_viewer','arguments':{},'_meta':{'threadId':'unrelated-install-check'}})['structuredContent']
    assert missing['view']=='select'
    conflict=rpc('tools/call',{'name':'open_rollout_viewer','arguments':{},'_meta':{'thread_id':data['trace']['threadId'],'threadId':'unrelated-install-check'}})['structuredContent']
    assert conflict['view']=='select'
    requests=[r for r in data['rows'] if r['type']=='request']
    toolrows=[r for r in data['rows'] if r['type']=='tool']
    if toolrows:
        focused=call('show_rollout_trace',{**a,'callId':toolrows[0]['id']})
        assert focused['focusCallId']==toolrows[0]['id'] and set(focused)=={'view','trace','focusCallId'}
        located=call('get_rollout_record',{**a,'callId':toolrows[0]['id']})['row']
        assert located['id']==toolrows[0]['id'] and located['callId']
    row=requests[-1]['id'];detail=call('get_rollout_detail',{**a,'rowId':row})
    assert detail['context']['complete'],'Last request has a missing prefix'
    projection=call('get_rollout_projection',a)
    assert projection['cells'] and all(cell['recordId'] for cell in projection['cells'])
    assert len(projection['requestNumbers'])==len(requests)
    private_names={'get_rollout_projection','get_rollout_cell_detail','read_rollout_cell_text','get_rollout_request_info','search_rollout_cells','get_rollout_binding'}
    assert all(tool['_meta']['ui']['visibility']==['app'] for tool in tools if tool['name'] in private_names)
    binding=call('get_rollout_binding',{'threadId':data['trace']['threadId']})
    assert set(binding)=={'currentThreadId','trace'} and binding['trace']['threadId']==data['trace']['threadId']
    info=call('get_rollout_request_info',{**a,'rowId':row})['request']
    assert info['cumulativeUsage'] and info['status']=='complete'
    first_cell=projection['cells'][0]
    metadata=call('get_rollout_cell_detail',{**a,'rowId':first_cell['rowId'],'cellKey':first_cell['cellKey']})
    assert metadata['fields'] and not metadata['cell']['detailsPending']
    field,description=next(iter(metadata['fields'].items()))
    hydration=[];position=0
    while position is not None:
        part=call('read_rollout_cell_text',{**a,'rowId':first_cell['rowId'],'cellKey':first_cell['cellKey'],
                  'field':field,'offset':position,'version':metadata['cell']['version']})
        hydration.append(part['text']);position=part['nextOffset']
    hydrated=''.join(hydration)
    assert len(hydrated)==description['totalChars']
    if description['json']:json.loads(hydrated)
    matches=call('search_rollout_cells',{**a,'query':'developer','rowIds':projection['rowIds']})
    assert matches['matches'],'Full-body search found no instruction records'
    pieces=[];offset=0
    while offset is not None:
        part=call('read_rollout_text',{**a,'rowId':row,'section':'full_context','offset':offset})
        pieces.append(part['text']);offset=part['nextOffset']
    content=''.join(pieces)
    assert all(text in content for text in args.expect_text),'Expected recorded content missing'
    links=0
    for tool in toolrows:
        detail=call('get_rollout_detail',{**a,'rowId':tool['id']})
        if detail['nextRequestId']:
            target=call('get_rollout_record',{**a,'rowId':detail['nextRequestId']})
            assert target['row']['type']=='request';links+=1
    resource=rpc('resources/read',{'uri':'ui://rollout-viewer/viewer.html'})['contents'][0]
    assert resource['mimeType']=='text/html;profile=mcp-app'
    current_uri=entry['_meta']['ui']['resourceUri']
    current_resource=rpc('resources/read',{'uri':current_uri})['contents'][0]
    assert version in current_uri and current_resource['text']==resource['text']
    source=Path(__file__).resolve().parents[1]/'plugins/codex-dsh-trace'
    files=['server/main.py','server/store.py','server/thread_index.py','server/projection.py','server/trajectory-locales.json','assets/viewer.html','.mcp.json','.codex-plugin/plugin.json','README.md']
    same=all(hashlib.sha256((source/f).read_bytes()).digest()==hashlib.sha256((root/f).read_bytes()).digest() for f in files)
    assert same,'Installed files differ from the current source'
    report={'version':version,'tools':len(tools),'installedFilesMatchSource':same,'mcpInitialization':True,'nativeEntryMetadata':True,'requests':data['requestCount'],'toolsInRecording':data['toolCount'],'expectedTextChecks':len(args.expect_text),'promptCharacters':len(content),'promptChunks':len(pieces),'verifiedToolNextRequestLinks':links,'appResourceBytes':len(resource['text'].encode()),'dshCells':len(projection['cells']),'lazyHydrationChunks':len(hydration),'fullBodySearch':True,'requestCumulativeUsage':True,'newToolsAppOnly':True,'nativeDesktopMountVerified':False}
    report.update(checkedInstalledFiles=files,codeCellsInRecording=data.get('codeCellCount',0),
                  fullContextSha256=hashlib.sha256(content.encode()).hexdigest(),exactRootBindingRpc=True,
                  callIdLaunchMetadataOnly=bool(toolrows),callIdLookup=bool(toolrows),
                  recordingSchemaVersion=data['trace'].get('schemaVersion',1))
    report['threadBindingMetadataOnly']=True
    report['versionedResourceAndLegacyAlias']=True
    if args.out:args.out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
finally:
    process.stdin.close()
    try:process.wait(timeout=10)
    except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=5)
