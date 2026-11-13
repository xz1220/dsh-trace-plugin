/* MCP Apps bridge. The loopback transport is only for authenticated local preview. */
export function createHost({onResult,onContext,onError}) {
  const preview=window.__ROLLOUT_PREVIEW__;
  const pending=new Map();let counter=0,ready=false,connecting,closed=false;
  const post=data=>window.parent.postMessage({jsonrpc:'2.0',...data},'*');
  const request=(method,params)=>new Promise((resolve,reject)=>{
    const id=`rollout-viewer-${++counter}`;
    const timer=setTimeout(()=>{pending.delete(id);reject(new Error('连接超时，请重试。'));},20000);
    pending.set(id,{resolve,reject,timer});post({id,method,params});
  });
  function receive(event){
    if(event.source!==window.parent||event.data?.jsonrpc!=='2.0')return;
    const message=event.data;
    if(message.id!==undefined&&!message.method&&pending.has(message.id)){
      const p=pending.get(message.id);pending.delete(message.id);clearTimeout(p.timer);
      message.error?p.reject(new Error(message.error.message||'工具调用失败')):p.resolve(message.result);return;
    }
    if(message.method==='ui/notifications/tool-result')onResult(message.params);
    if(message.method==='ui/notifications/host-context-changed')onContext(message.params||{});
    if(message.method==='ui/resource-teardown'){
      if(message.id!==undefined)post({id:message.id,result:{}});
      dispose();
    }
  }
  function globals(event){const data=event.detail?.globals||{};onContext(data);if(data.toolOutput)onResult({structuredContent:data.toolOutput});}
  function dispose(){closed=true;window.removeEventListener('message',receive);window.removeEventListener('openai:set_globals',globals);for(const p of pending.values()){clearTimeout(p.timer);p.reject(new Error('面板已关闭'));}pending.clear();}
  async function start(){
    if(preview){ready=true;return;}
    if(connecting)return connecting;
    connecting=Promise.resolve().then(async()=>{
      window.addEventListener('message',receive);window.addEventListener('openai:set_globals',globals);
      if(window.openai?.toolOutput)onResult({structuredContent:window.openai.toolOutput});
      return request('ui/initialize',{protocolVersion:'2026-01-26',appInfo:{name:'Rollout Viewer',version:'0.2.7'},appCapabilities:{}});
    }).then(result=>{
      if(result.protocolVersion!=='2026-01-26')throw new Error('宿主版本不支持此面板。');
      ready=true;onContext(result.hostContext||{});post({method:'ui/notifications/initialized'});
    }).catch(error=>{onError(error);throw error;});
    return connecting;
  }
  return {preview,start,dispose,async call(name,args={}){
    if(closed)throw new Error('面板已关闭');
    let result;
    if(preview){
      const response=await fetch('/api',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,arguments:args})});
      result=await response.json();if(!response.ok)throw new Error(result.error||'本地服务不可用。');
    }else{
      if(!ready)await start();
      result=await request('tools/call',{name,arguments:args});
    }
    if(result.isError||result.structuredContent?.error)throw new Error(result.structuredContent?.error||result.content?.find(x=>x.type==='text')?.text||'读取失败');
    return result.structuredContent||result;
  }};
}
