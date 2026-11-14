import React, {useCallback, useEffect, useRef, useState} from 'react';
import {IconCopyOutlineRegular, IconChevronRightOutlineRegular, JsonTree, MarkdownText} from '../vendor/dsh/primitives.ts';
import table from '../vendor/dsh/packages/client/ui-trajectory/src/client/TrajectoryTable.module.css';
import {useTranslation} from './locale-context.jsx';

export function Failure({error,retry}) {
  const t=useTranslation();
  return <div className="app-error" role="alert"><strong>{t.text('未能读取','Unable to read')}</strong><p>{error}</p>
    {retry&&<button type="button" className="app-link" onClick={retry}>{t('retry')}</button>}</div>;
}
export function Skeleton() {
  const t=useTranslation();
  return <div className="app-skeleton" role="status" aria-label={t.text('正在读取内容','Loading content')}><i/><i/><i/></div>;
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
  const t=useTranslation(),text=t.text;
  const labels={copyValue:t('copy.value'),copyJson:t('copy.json'),copyPath:t('copy.path'),copyPrettyJson:t('copy.prettyJson'),copyCompactJson:t('copy.compactJson'),copied:t('copied'),copyFailed:t('copy.failed'),collapseNode:t('collapse'),expandNode:t('expand'),copyButtonTitle:action=>t('copy.optionsHint',{action})};
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
    <div className="app-content-toolbar"><span>{label}{data&&` · ${data.totalChars.toLocaleString()} ${text('字符','characters')}`}</span>
      <div>{json!==undefined&&<button type="button" className="app-button" aria-pressed={tree} onClick={()=>setTree(!tree)}>{tree?text('原文','Raw'):text('树形','Tree')}</button>}
        <button type="button" className="app-button" aria-pressed={wrap} onClick={()=>setWrap(!wrap)}>{text('换行','Wrap')}</button>
        <button type="button" className="app-icon" disabled={busy||data?.available===false} aria-label={text(`复制完整${label}`,`Copy complete ${label}`)} title={text(`复制完整${label}`,`Copy complete ${label}`)} onClick={copyAll}><IconCopyOutlineRegular size={14}/></button></div></div>
    {error&&<Failure error={error} retry={()=>load(data?.nextOffset||0)}/>}
    {!data&&!error?<Skeleton/>:data?.available===false?<p className={table.noPayload}>{text('录制中没有此内容。','This content is not in the recording.')}</p>:
      json!==undefined&&tree?<JsonTree data={json} label={label} labels={labels} collapsedStringLines={12} className={table.jsonPayload}/>:
      <pre className={`${table.payload} app-raw`} data-wrap={wrap}>{data?.text}</pre>}
    {data?.nextOffset!==null&&data?.nextOffset!==undefined&&<button className="app-load-more" disabled={busy} onClick={()=>load(data.nextOffset)}>
      {busy?text('正在读取…','Loading…'):text(`继续加载（${data.nextOffset.toLocaleString()} / ${data.totalChars.toLocaleString()} 字符）`,`Load more (${data.nextOffset.toLocaleString()} / ${data.totalChars.toLocaleString()} characters)`)}</button>}
  </section>;
}

function PromptContext({request,detail,api,copy}) {
  const t=useTranslation(),text=t.text;
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
      <strong>{!context.complete?text('前序录制缺失，以下是已知上下文','Earlier recording missing; showing known context'):context.incremental?text('已沿响应链恢复完整上下文','Complete context restored along the response chain'):text('客户端实际请求输入','Recorded client request input')}</strong>
      <span>{context.incremental?text('继承输入、前序模型输出和本次增量分别标记。','Inherited input, previous output and current increment are labelled.'):text('按录制保留原始角色和输入顺序。','Original roles and input order are preserved.')}</span>
    </div>
    <div className="app-prompt-controls"><div role="group" aria-label={text('上下文范围','Context scope')}>
      <button type="button" className="app-button" aria-pressed={mode==='full'} onClick={()=>setMode('full')}>{context.complete?t('codex.prompt'):text('已知上下文','Known context')} {messages.length}</button>
      {context.incremental&&<button type="button" className="app-button" aria-pressed={mode==='delta'} onClick={()=>setMode('delta')}>{text('本次增量','Current increment')} {messages.filter(m=>!m.inherited).length}</button>}
    </div><button type="button" className="app-icon" disabled={copying} aria-label={context.complete?text('复制完整上下文','Copy complete context'):text('复制已知上下文','Copy known context')} onClick={copyContext}><IconCopyOutlineRegular size={14}/></button></div>
    <div className="app-prompt-filter"><select aria-label={text('筛选提示词角色','Filter input roles')} value={role} onChange={e=>{setRole(e.target.value);setExpanded(null);}}>
      <option value="all">{text('全部角色','All roles')}</option>{[...new Set(messages.map(m=>m.role))].map(value=><option key={value} value={value}>{value}</option>)}</select><span>{visible.length} {text('条输入','items')}</span></div>
    {error&&<Failure error={error} retry={copyContext}/>}
    {visible.map(message=><section className="app-message" key={message.index}>
      <button type="button" className="app-message-heading" aria-expanded={opened===message.index} onClick={()=>setExpanded(opened===message.index?-1:message.index)}>
        <IconChevronRightOutlineRegular size={11} style={{transform:opened===message.index?'rotate(90deg)':undefined}}/>
        <span className="app-role">{message.role}</span><strong title={message.preview||message.label}>{message.preview||message.label}</strong>
        <em>{message.inherited?text('继承','Inherited'):''}</em><small>{message.chars.toLocaleString()} {text('字','chars')}</small>
      </button>
      {opened===message.index&&<><div className="app-message-origin">{text('输入项','Item')} {message.index+1} · {message.origin==='response'?text('前序模型输出','Previous model output'):text('请求输入','Request input')}</div>
        {message.hasEncryptedContent&&<p className="app-note">{text('包含不透明的加密数据。','Contains opaque encrypted data.')}</p>}
        <TextContent key={message.index} rowId={request.rowId} section="message" itemIndex={message.index} api={api} copy={copy} label={`${message.role} ${message.label}`}/></>}
    </section>)}
    {!visible.length&&<p className={table.noPayload}>{text('没有符合此角色的输入项。','No input items match this role.')}</p>}
    <details className="app-tool-catalog"><summary>{text('工具声明','Tool declarations')}</summary><TextContent rowId={request.rowId} section="tools" api={api} copy={copy} label={text('工具声明 JSON','Tool declarations JSON')}/></details>
  </>;
}

export function RequestContent({traceId,request,tab,call,copy}) {
  const t=useTranslation();
  const [detail,setDetail]=useState(null),[error,setError]=useState(''),[retry,setRetry]=useState(0);
  const api=useCallback((name,args)=>call(name,{traceId,...args}),[traceId,call]);
  useEffect(()=>{
    let active=true;setDetail(null);setError('');
    if(tab==='codex-prompt')api('get_rollout_detail',{rowId:request.rowId}).then(value=>{if(active)setDetail(value);}).catch(e=>{if(active)setError(e.message);});
    return()=>{active=false;};
  },[api,request.rowId,tab,retry]);
  if(tab==='codex-request'||tab==='codex-response')return <TextContent rowId={request.rowId} section={tab==='codex-request'?'raw_request':'response'} api={api} copy={copy} label={`${t(tab==='codex-request'?'codex.request':'codex.response')} JSON`}/>;
  if(tab!=='codex-prompt')return null;
  if(request.purpose==='compaction')return <TextContent rowId={request.rowId} section="raw_request" api={api} copy={copy} label={t.text('压缩请求 JSON','Compaction request JSON')}/>;
  return error?<Failure error={error} retry={()=>setRetry(v=>v+1)}/>:detail?<PromptContext key={request.rowId} {...{request,detail,api,copy}}/>:<Skeleton/>;
}
