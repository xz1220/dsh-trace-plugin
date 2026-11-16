import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {McpClient} from '../plugins/antigravity-dsh-trace/sidecars/trace-viewer/rpc-client.mjs';
import {makeToolRequest} from '../plugins/antigravity-dsh-trace/sidecars/trace-viewer/tool-request.mjs';

const backend = `
const readline=require('node:readline');
readline.createInterface({input:process.stdin}).on('line',line=>{
 const m=JSON.parse(line);if(m.id===undefined)return;
 if(m.method==='initialize'){process.stdout.write(JSON.stringify({jsonrpc:'2.0',id:m.id,result:{protocolVersion:'2025-06-18'}})+'\\n');return;}
 if(m.params.name==='exit'){process.exit(7);return;}
 if(m.params.name==='hang')return;
 setTimeout(()=>process.stdout.write(JSON.stringify({jsonrpc:'2.0',id:m.id,result:{structuredContent:m.params}})+'\\n'),m.params.arguments.delay||0);
});`;

function reader(t, options = {}) {
  const client = new McpClient({command:process.execPath,args:['-e',backend],timeoutMs:2000,...options});
  t.after(() => client.close());
  return client;
}

test('reader pairs out-of-order concurrent responses with their original pane metadata', async t => {
  const client = reader(t);
  const first = makeToolRequest({name:'get_rollout_delta',arguments:{traceId:'native:first',delay:30},conversationId:'first'});
  const second = makeToolRequest({name:'get_rollout_delta',arguments:{traceId:'native:second',delay:1},conversationId:'second'});
  const [a,b] = await Promise.all([client.call(first),client.call(second)]);
  assert.deepEqual(a.structuredContent,first);
  assert.deepEqual(b.structuredContent,second);
  assert.equal(client.pending.size,0);
});

test('backend failure rejects pending requests and the next call starts a fresh reader', async t => {
  const client = reader(t);
  await assert.rejects(client.call({name:'exit',arguments:{}}),/stopped|connection closed/);
  const result = await client.call({name:'recovered',arguments:{}});
  assert.equal(result.structuredContent.name,'recovered');
});

test('reader timeout and teardown settle pending requests without retaining callbacks', async t => {
  const client = reader(t,{timeoutMs:200});
  await assert.rejects(client.call({name:'hang',arguments:{}}),/timed out/);
  assert.equal(client.pending.size,0);
  const pending = client.call({name:'hang',arguments:{}});
  await new Promise(resolve=>setImmediate(resolve));
  client.close();
  await assert.rejects(pending,/closed/);
  await assert.rejects(client.call({name:'anything',arguments:{}}),/closed/);
});

test('pane binding rejects another conversation or trace and cannot be overridden by supplied metadata', () => {
  assert.throws(()=>makeToolRequest({name:'get_rollout_binding',arguments:{threadId:'other'},conversationId:'current'}),/does not belong/);
  assert.throws(()=>makeToolRequest({name:'get_rollout_detail',arguments:{traceId:'native:other'},conversationId:'current'}),/does not belong/);
  assert.throws(()=>makeToolRequest({name:'get_rollout_detail',arguments:{traceId:'codex-recording'},conversationId:'current'}),/does not belong/);
  assert.throws(()=>makeToolRequest({name:'open_rollout_viewer',conversationId:'../outside'}),/from a conversation/);
  assert.throws(()=>makeToolRequest({name:'add_rollout_directory',arguments:{path:'/tmp'},conversationId:'current'}),/Unsupported/);
  const request = makeToolRequest({name:'open_rollout_viewer',conversationId:'current',_meta:{threadId:'codex',conversationId:'other'}});
  assert.deepEqual(request._meta,{host:'antigravity',conversationId:'current'});
});

function hostHarness({background='',pixels=[255,255,255,255],dark=false}={}) {
  const handlers = new Map(), replies = [], calls = [];
  const painted=[];
  const parent = {};
  const child = {postMessage:(message,origin)=>replies.push({message,origin})};
  const root = {style:{colorScheme:''},appendChild(){}};
  const document = {
    documentElement:root,
    getElementById:()=>({contentWindow:child}),
    createElement:type=>type==='canvas'?{getContext:()=>({
      set fillStyle(value){painted.push(value);},
      fillRect(){},getImageData:()=>({data:pixels}),
    })}:{style:{},remove(){}},
  };
  const window = {parent,sidecar:{conversationId:'pane-current',fetch:async(url,options)=>{
    calls.push({url,...options});return {ok:true,json:async()=>({structuredContent:{view:'select'}})};
  }},addEventListener:(type,fn)=>handlers.set(type,fn),removeEventListener(){}};
  const sandbox = {window,document,navigator:{language:'en-US'},location:{origin:'http://127.0.0.1:5555',search:''},
    matchMedia:()=>({matches:dark}),getComputedStyle:element=>element===root?{getPropertyValue:()=>background}:{color:background},
    MutationObserver:class{observe(){}disconnect(){}},URLSearchParams,AbortController,setTimeout,clearTimeout};
  vm.runInNewContext(readFileSync(new URL('../plugins/antigravity-dsh-trace/sidecars/trace-viewer/host.js',import.meta.url),'utf8'),sandbox);
  return {parent,child,handlers,replies,calls,painted,send:event=>handlers.get('message')(event)};
}

test('browser bridge accepts only its own same-origin viewer and binds every request to the current pane', async()=>{
  const state=hostHarness();
  const request={jsonrpc:'2.0',id:10,method:'tools/call',params:{name:'open_rollout_viewer',arguments:{},_meta:{conversationId:'other'}}};
  await state.send({source:{},origin:'http://127.0.0.1:5555',data:request});
  await state.send({source:state.child,origin:'https://unrelated.invalid',data:request});
  assert.equal(state.calls.length,0);
  await state.send({source:state.child,origin:'http://127.0.0.1:5555',data:request});
  assert.equal(state.calls.length,1);
  assert.deepEqual(JSON.parse(state.calls[0].body),{name:'open_rollout_viewer',arguments:{},conversationId:'pane-current'});
  assert.equal(state.replies[0].origin,'http://127.0.0.1:5555');
  assert.equal(state.replies[0].message.id,10);
});

test('browser bridge initializes the shared viewer and sends native host context updates', async()=>{
  const state=hostHarness();
  await state.send({source:state.child,origin:'http://127.0.0.1:5555',data:{jsonrpc:'2.0',id:'init',method:'ui/initialize'}});
  assert.equal(state.replies[0].message.result.hostInfo.name,'Antigravity');
  assert.equal(state.replies[0].message.result.hostContext.locale,'en-US');
  await state.send({source:state.child,origin:'http://127.0.0.1:5555',data:{jsonrpc:'2.0',method:'ui/notifications/initialized'}});
  await state.send({source:state.parent,data:{type:'theme-change',payload:{theme:'dark',locale:'zh-CN'}}});
  const update=state.replies.at(-1).message;
  assert.equal(update.method,'ui/notifications/host-context-changed');
  assert.equal(update.params.theme,'dark');
  assert.equal(update.params.locale,'zh-CN');
});

test('explicit host theme wins over CSS color syntax and the previous OS scheme',async()=>{
  const state=hostHarness({background:'oklch(0.98 0 0)',pixels:[249,249,249,255],dark:true});
  await state.send({source:state.child,origin:'http://127.0.0.1:5555',data:{jsonrpc:'2.0',method:'ui/notifications/initialized'}});
  await state.send({source:state.parent,data:{type:'theme-change',payload:{theme:'light',locale:'en-US',cssVariables:{'--background':'oklch(0.98 0 0)'}}}});
  assert.equal(state.replies.at(-1).message.params.theme,'light');
  assert.equal(state.replies.at(-1).message.params.locale,'en-US');
  assert.equal(state.painted.length,0);
});

test('CSS-only host colors are converted to sRGB before choosing the viewer scheme',async()=>{
  for(const [background,pixels,expected] of [
    ['rgb(250, 250, 250)',[250,250,250,255],'light'],
    ['rgba(20, 20, 20, 1)',[20,20,20,255],'dark'],
    ['oklch(0.98 0 0)',[249,249,249,255],'light'],
    ['oklab(0.12 0 0)',[6,6,6,255],'dark'],
    ['color(display-p3 0.97 0.98 0.99)',[247,250,252,255],'light'],
  ]){
    const state=hostHarness({background,pixels,dark:expected==='light'});
    await state.send({source:state.child,origin:'http://127.0.0.1:5555',data:{jsonrpc:'2.0',id:'init',method:'ui/initialize'}});
    assert.equal(state.replies[0].message.result.hostContext.theme,expected,background);
    assert.deepEqual(state.painted,[background]);
  }
});
