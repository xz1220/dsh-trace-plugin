import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createHost} from '../src/host.js';

function setup(t,{output,open}={}){
  const previous=globalThis.window,handlers=new Map(),calls=[],results=[],errors=[];
  const send=value=>handlers.get('message')?.({source:parent,data:{jsonrpc:'2.0',...value}});
  const parent={postMessage(message){
    calls.push(message);
    if(message.id===undefined)return;
    Promise.resolve().then(async()=>{
      const result=message.method==='ui/initialize'?{protocolVersion:'2026-01-26',hostContext:{theme:'light'}}:await open?.(message.params);
      send({id:message.id,result});
    });
  }};
  globalThis.window={parent,openai:{toolOutput:output},
    addEventListener:(type,handler)=>handlers.set(type,handler),
    removeEventListener:(type,handler)=>{if(handlers.get(type)===handler)handlers.delete(type);}};
  const host=createHost({onResult:value=>results.push(value.structuredContent||value),onContext:()=>{},onError:error=>errors.push(error.message)});
  t.after(()=>{host.dispose();globalThis.window=previous;});
  return {host,calls,results,errors,send};
}

test('cold sidebar reads its existing history without a model notification',async t=>{
  const history={view:'trace',currentThreadId:'root',trace:{id:'old'},rows:[{id:'request:old'}]};
  const state=setup(t,{open:params=>{assert.equal(params.name,'open_rollout_viewer');return {structuredContent:history};}});
  await state.host.start();
  assert.deepEqual(state.results,[history]);
  assert.deepEqual(state.calls.map(call=>call.method),['ui/initialize','ui/notifications/initialized','tools/call']);
  assert.deepEqual(state.errors,[]);
});

test('unrelated initial tool output does not suppress the history read',async t=>{
  const history={view:'trace',trace:{id:'history'},rows:[]};
  const state=setup(t,{output:{traces:[]},open:()=>({structuredContent:history})});
  await state.host.start();
  assert.deepEqual(state.results,[history]);
  assert.equal(state.calls.filter(call=>call.method==='tools/call').length,1);
});

test('a supplied native launch does not issue a second startup read',async t=>{
  const launch={view:'open',trace:{id:'supplied'}};
  const state=setup(t,{output:launch});
  await state.host.start();
  assert.deepEqual(state.results,[launch]);
  assert.equal(state.calls.some(call=>call.method==='tools/call'),false);
});

test('a delayed startup read cannot replace a newer explicit launch',async t=>{
  let complete,started;
  const waiting=new Promise(resolve=>{started=resolve;});
  const state=setup(t,{open:()=>{started();return new Promise(resolve=>{complete=resolve;});}});
  const ready=state.host.start();await waiting;
  const newer={view:'open',trace:{id:'explicit'}};
  state.send({method:'ui/notifications/tool-result',params:{structuredContent:newer}});
  complete({structuredContent:{view:'select',traces:[]}});await ready;
  assert.deepEqual(state.results,[newer]);
});

test('startup tool errors are reported rather than leaving an empty loading view',async t=>{
  const state=setup(t,{open:()=>({isError:true,structuredContent:{error:'Capture unavailable'}})});
  await assert.rejects(state.host.start(),/Capture unavailable/);
  assert.deepEqual(state.errors,['Capture unavailable']);
  assert.deepEqual(state.results,[]);
});
