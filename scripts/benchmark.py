"""Measure real recording reads plus a 10,000-row synthetic scaling fixture."""
import argparse
import json
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'plugins/rollout-viewer/server'))
sys.path.insert(0,str(ROOT/'tests'))
from store import Store
from test_store import Fixture

def timed(fn):
    start=time.perf_counter();value=fn();return value,(time.perf_counter()-start)*1000

def sample(index):
    data,cold=timed(index.overview)
    before=index.metrics.copy()
    warm=[timed(index.overview)[1] for _ in range(30)]
    delta=[timed(lambda:index.delta(data['revision']))[1] for _ in range(30)]
    return {'rows':data['totalRows'],'initialIndexMs':round(cold,3),
            'warmPageP50Ms':round(statistics.median(warm),3),
            'warmPageP95Ms':round(sorted(warm)[28],3),
            'unchangedPollP50Ms':round(statistics.median(delta),3),
            'initialPayloadReads':before['payloadReads'],
            'warmExtraLogBytes':index.metrics['logBytesRead']-before['logBytesRead']}

def projection_sample(store,index):
    before=index.metrics['payloadReads']
    page,elapsed=timed(lambda:store.projection(index.meta['id']).page())
    return {'initialProjectionMs':round(elapsed,3),'projectedCells':len(page['cells']),
            'projectionPayloadReads':index.metrics['payloadReads']-before,
            'projectionResponseBytes':len(json.dumps(page,ensure_ascii=False).encode())}

parser=argparse.ArgumentParser();parser.add_argument('--trace-id',required=True);parser.add_argument('--out',type=Path);args=parser.parse_args()
store=Store();index=store.index(args.trace_id);real=sample(index)
row=[r for r in index.rows.values() if r.get('type')=='request'][-1]
detail,ms=timed(lambda:store.details(args.trace_id,row['id']))
real['fullContextMetadataMs']=round(ms,3);real['messages']=len(detail['messages']);real['contextComplete']=detail['context']['complete']
real.update(projection_sample(store,index))
with tempfile.TemporaryDirectory() as temporary:
    root=Path(temporary);f=Fixture(root/'bundle')
    ref=f.payload({'input':[]},'inference_request')
    events=[]
    for n in range(10000):
        events.append(f.event('inference_started',inference_call_id=str(n),model='test',request_payload=ref))
        events.append(f.event('inference_completed',inference_call_id=str(n),response_id=f'r{n}',response_payload=None))
    (f.root/'trace.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
    test=Store(root/'config.json');test.catalog.default_root=root/'default';test.catalog.register(str(f.root))
    synthetic=sample(test.index('trace-test'))
    synthetic.update(projection_sample(test,test.index('trace-test')))
report={'pluginVersion':json.loads((ROOT/'package.json').read_text())['version'],'python':platform.python_version(),'platform':platform.machine(),'realRecording':real,'synthetic10000Rows':synthetic,
        'scope':'Local backend timings; OS filesystem cache may already be warm. UI and MCP bridge latency are measured separately.'}
if args.out:args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
