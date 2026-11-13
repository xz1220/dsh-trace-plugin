import React, {useCallback, useEffect, useRef, useState} from 'react';
import {IconCopyOutlineRegular, IconChevronRightOutlineRegular, JsonTree, MarkdownText} from '../vendor/dsh/primitives.ts';
import table from '../vendor/dsh/packages/client/ui-trajectory/src/client/TrajectoryTable.module.css';

export const jsonLabels = {
  copyValue:'复制值', copyJson:'复制 JSON', copyPath:'复制路径', copyPrettyJson:'复制格式化 JSON',
  copyCompactJson:'复制紧凑 JSON', copied:'已复制', copyFailed:'复制失败',
  collapseNode:'收起节点', expandNode:'展开节点', copyButtonTitle:action=>`${action}，右键查看更多选项`,
};
export function Failure({error,retry}) {
  return <div className="app-error" role="alert"><strong>未能读取</strong><p>{error}</p>
    {retry&&<button type="button" className="app-link" onClick={retry}>重试</button>}</div>;
}
export function Skeleton() {
  return <div className="app-skeleton" role="status" aria-label="正在读取内容"><i/><i/><i/></div>;
}
export async function readComplete(api, name, arguments_, isCurrent=()=>true) {
  let text='', offset=0;
  while(offset!==null) {
    if(!isCurrent()) throw new Error('读取已取消');
    const result=await api(name,{...arguments_,offset});
    if(result.available===false) return null;
    text+=result.text;
    if(result.nextOffset!==null&&result.nextOffset<=offset) throw new Error('内容分页没有前进，请重新打开录制。');
    offset=result.nextOffset;
  }
  return text;
}

export function TextContent({rowId, section, itemIndex, api, copy, label}) {
  const [data,setData]=useState(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [wrap,setWrap]=useState(true),[tree,setTree]=useState(true);
  const ticket=useRef(0), dataRef=useRef(null);
  const load=useCallback(async(offset=0)=>{
    const id=++ticket.current; setBusy(true); setError('');
    try {
      const value=await api('read_rollout_text',{rowId,section,...(itemIndex!==undefined?{itemIndex}:{}),offset});
      if(id!==ticket.current) return;
      const next={...value,text:offset?(dataRef.current?.text||'')+value.text:value.text};
      dataRef.current=next;setData(next);
    } catch(e) {if(id===ticket.current)setError(e.message);}
    finally {if(id===ticket.current)setBusy(false);}
  },[api,rowId,section,itemIndex]);
  useEffect(()=>{setData(null);dataRef.current=null;setError('');load();return()=>{ticket.current++;};},[load]);
  async function copyAll() {
    const id=ticket.current;setBusy(true);setError('');
    try {const text=await readComplete(api,'read_rollout_text',{rowId,section,...(itemIndex!==undefined?{itemIndex}:{})},()=>ticket.current===id);if(text!==null)await copy(text);}
    catch(e){if(ticket.current===id)setError(e.message);}
    finally{if(ticket.current===id)setBusy(false);}
  }
  let json;
  if(data?.available&&data.nextOffset===null&&data.text.length<250000) {
    try {json=JSON.parse(data.text);} catch {}
  }
  return <section className="app-text" aria-label={label}>
    <div className="app-content-toolbar"><span>{label}{data&&` · ${data.totalChars.toLocaleString()} 字符`}</span>
      <div>{json!==undefined&&<button type="button" className="app-button" aria-pressed={tree} onClick={()=>setTree(!tree)}>{tree?'原文':'树形'}</button>}
        <button type="button" className="app-button" aria-pressed={wrap} onClick={()=>setWrap(!wrap)}>换行</button>
        <button type="button" className="app-icon" disabled={busy||data?.available===false} aria-label={`复制完整${label}`} title={`复制完整${label}`} onClick={copyAll}><IconCopyOutlineRegular size={14}/></button></div></div>
    {error&&<Failure error={error} retry={()=>load(data?.nextOffset||0)}/>}
    {!data&&!error?<Skeleton/>:data?.available===false?<p className={table.noPayload}>录制中没有此内容。</p>:
      json!==undefined&&tree?<JsonTree data={json} label={label} labels={jsonLabels} collapsedStringLines={12} className={table.jsonPayload}/>:
      <pre className={`${table.payload} app-raw`} data-wrap={wrap}>{data?.text}</pre>}
    {data?.nextOffset!==null&&data?.nextOffset!==undefined&&<button className="app-load-more" disabled={busy} onClick={()=>load(data.nextOffset)}>
      {busy?'正在读取…':`继续加载（${data.nextOffset.toLocaleString()} / ${data.totalChars.toLocaleString()} 字符）`}</button>}
  </section>;
}

function PromptContext({request,detail,api,copy}) {
  const [mode,setMode]=useState('full'),[role,setRole]=useState('all'),[expanded,setExpanded]=useState(null);
  const [copying,setCopying]=useState(false),[error,setError]=useState('');
  const {context,messages}=detail;
  // Even when a prefix is missing, preserve the known inherited items.
  const current=messages.filter(message=>mode==='full'||!message.inherited);
  const visible=current.filter(message=>role==='all'||message.role===role);
  const opened=expanded===null?visible.find(message=>message.type!=='additional_tools')?.index:expanded;
  async function copyContext(){
    setCopying(true);setError('');
    try {const text=await readComplete(api,'read_rollout_text',{rowId:request.rowId,section:'full_context'});await copy(text||'');}
    catch(e){setError(e.message);}finally{setCopying(false);}
  }
  return <>
    <div className="app-context-note" data-incomplete={!context.complete||undefined}>
      <strong>{!context.complete?'前序录制缺失，以下是已知上下文':context.incremental?'已沿响应链恢复完整上下文':'客户端实际请求输入'}</strong>
      <span>{context.incremental?'继承输入、前序模型输出和本次增量分别标记。':'按录制保留原始角色和输入顺序。'}</span>
    </div>
    <div className="app-prompt-controls"><div role="group" aria-label="上下文范围">
      <button type="button" className="app-button" aria-pressed={mode==='full'} onClick={()=>setMode('full')}>{context.complete?'完整上下文':'已知上下文'} {messages.length}</button>
      {context.incremental&&<button type="button" className="app-button" aria-pressed={mode==='delta'} onClick={()=>setMode('delta')}>本次增量 {messages.filter(m=>!m.inherited).length}</button>}
    </div><button type="button" className="app-icon" disabled={copying} aria-label={context.complete?'复制完整上下文':'复制已知上下文'} onClick={copyContext}><IconCopyOutlineRegular size={14}/></button></div>
    <div className="app-prompt-filter"><select aria-label="筛选提示词角色" value={role} onChange={e=>{setRole(e.target.value);setExpanded(null);}}>
      <option value="all">全部角色</option>{[...new Set(messages.map(m=>m.role))].map(value=><option key={value} value={value}>{value}</option>)}</select><span>{visible.length} 条输入</span></div>
    {error&&<Failure error={error} retry={copyContext}/>}
    {visible.map(message=><section className="app-message" key={message.index}>
      <button type="button" className="app-message-heading" aria-expanded={opened===message.index} onClick={()=>setExpanded(opened===message.index?-1:message.index)}>
        <IconChevronRightOutlineRegular size={11} style={{transform:opened===message.index?'rotate(90deg)':undefined}}/>
        <span className="app-role">{message.role}</span><strong title={message.preview||message.label}>{message.preview||message.label}</strong>
        <em>{message.inherited?'继承':''}</em><small>{message.chars.toLocaleString()} 字</small>
      </button>
      {opened===message.index&&<><div className="app-message-origin">输入项 {message.index+1} · {message.origin==='response'?'前序模型输出':'请求输入'}</div>
        {message.hasEncryptedContent&&<p className="app-note">包含不透明的加密数据。</p>}
        <TextContent key={message.index} rowId={request.rowId} section="message" itemIndex={message.index} api={api} copy={copy} label={`${message.role} ${message.label}`}/></>}
    </section>)}
    {!visible.length&&<p className={table.noPayload}>没有符合此角色的输入项。</p>}
    <details className="app-tool-catalog"><summary>工具声明</summary><TextContent rowId={request.rowId} section="tools" api={api} copy={copy} label="工具声明 JSON"/></details>
  </>;
}

export function RequestContent({traceId,request,tab,call,copy}) {
  const [detail,setDetail]=useState(null),[error,setError]=useState(''),[retry,setRetry]=useState(0);
  const api=useCallback((name,args)=>call(name,{traceId,...args}),[traceId,call]);
  useEffect(()=>{
    let active=true;setDetail(null);setError('');
    if(tab==='codex-prompt')api('get_rollout_detail',{rowId:request.rowId}).then(value=>{if(active)setDetail(value);}).catch(e=>{if(active)setError(e.message);});
    return()=>{active=false;};
  },[api,request.rowId,tab,retry]);
  if(tab==='codex-request'||tab==='codex-response')return <TextContent rowId={request.rowId} section={tab==='codex-request'?'raw_request':'response'} api={api} copy={copy} label={tab==='codex-request'?'原始请求 JSON':'原始响应 JSON'}/>;
  if(tab!=='codex-prompt')return null;
  if(request.purpose==='compaction')return <TextContent rowId={request.rowId} section="raw_request" api={api} copy={copy} label="压缩请求 JSON"/>;
  return error?<Failure error={error} retry={()=>setRetry(v=>v+1)}/>:detail?<PromptContext key={request.rowId} {...{request,detail,api,copy}}/>:<Skeleton/>;
}
