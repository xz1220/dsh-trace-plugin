import React,{useState,useEffect,useRef,useCallback,useMemo} from 'react';
import {createRoot} from 'react-dom/client';
import '../vendor/dsh/packages/client/ui-theme/src/styles/base.css';
import '../vendor/dsh/packages/client/ui-theme/src/styles/design-platform.css';
import '../vendor/dsh/packages/client/ui-theme/src/styles/focus.css';
import '../vendor/dsh/packages/client/ui-theme/src/styles/gradient-shadow-text.css';
import view from '../vendor/dsh/packages/client/ui-trajectory/src/client/views.module.css';
import './viewer.css';
import {createHost} from './host.js';
import {Failure,Skeleton} from './content.jsx';
import Trajectory from './Trajectory.jsx';
import {installIconSprite} from '../vendor/dsh/packages/client/ui-theme/src/client/icon-sprite.ts';
import {disposeImageTransfers} from './images.jsx';
import {LocaleContext} from './locale-context.jsx';
import {translatorFor,normalizeLocale,supportedLocales} from './locale.js';

const statusNames={running:'进行中',complete:'已结束',error:'失败',cancelled:'已取消'};
const timeLabel=value=>typeof value==='number'?new Date(value).toLocaleString(undefined,{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}):'时间未知';
const quoteShell=value=>`'${String(value).replaceAll("'", "'\"'\"'")}'`;

function App(){
  const host=useRef(),received=useRef(false),generation=useRef(0),earlierBusy=useRef(false),toastTimer=useRef();
  const [data,setData]=useState(null),[traces,setTraces]=useState([]),[loading,setLoading]=useState(true),[error,setError]=useState('');
  const [thread,setThread]=useState('all'),[dark,setDark]=useState(false),[live,setLive]=useState(true),[toast,setToast]=useState('');
  const [directory,setDirectory]=useState(''),[adding,setAdding]=useState(false),[rootPath,setRootPath]=useState('');
  const [focusCallId,setFocusCallId]=useState(null);
  const [locale,setLocale]=useState('zh');
  const t=useMemo(()=>translatorFor(locale),[locale]);
  const text=t.text;
  const call=useCallback((name,args={})=>host.current?host.current.call(name,args):Promise.reject(new Error('面板正在连接。')),[]);
  const notify=useCallback(text=>{setToast(text);clearTimeout(toastTimer.current);toastTimer.current=setTimeout(()=>setToast(''),2200);},[]);
  const copy=useCallback(async value=>{try{await navigator.clipboard.writeText(value);notify(text('已复制完整内容','Complete content copied'));}catch{notify(text('复制失败，请选择文本复制','Copy failed; select the text to copy'));}},[notify,text]);
  const loadTrace=useCallback(async(id,focus=null)=>{
    if(!id)return;
    const ticket=++generation.current;setLoading(true);setError('');
    try{
      let value=await call('get_rollout_overview',{traceId:id});
      if(focus){
        const {row}=await call('get_rollout_record',{traceId:id,callId:focus});
        focus=row.callId;
        while(value.hasEarlier&&value.beforeSeq>row.seq){
          if(ticket!==generation.current)return;
          const page=await call('get_rollout_overview',{traceId:id,beforeSeq:value.beforeSeq,limit:200});
          if(!page.rows.length||page.beforeSeq>=value.beforeSeq)throw new Error('历史分页没有前进，请重试。');
          const rows=new Map([...page.rows,...value.rows].map(record=>[record.id,record]));
          value={...value,rows:[...rows.values()].sort((a,b)=>a.seq-b.seq),beforeSeq:page.beforeSeq,hasEarlier:page.hasEarlier};
        }
      }
      if(ticket!==generation.current)return;setData(value);setThread('all');setFocusCallId(focus);setLoading(false);
    }
    catch(e){if(ticket===generation.current){setError(e.message);setLoading(false);}}
  },[call]);
  useEffect(()=>{
    let active=true;
    function apply(value){
      if(!active)return;received.current=true;
      if(value.view==='open'){loadTrace(value.trace.id,value.focusCallId||null);return;}
      if(value.rows){generation.current++;setData(value);setThread('all');setFocusCallId(null);setLoading(false);setError('');return;}
      if(value.view==='select'){generation.current++;setTraces(value.traces||[]);setRootPath(value.defaultRoot||'');setData(null);setFocusCallId(null);setThread('all');setLoading(false);setError('');}
    }
    const bridge=createHost({onResult:result=>apply(result.structuredContent||result),onContext:context=>{if(!active)return;if(context.theme)setDark(context.theme==='dark');if(context.locale)setLocale(normalizeLocale(context.locale));},onError:e=>{if(active){setError(e.message);setLoading(false);}}});
    host.current=bridge;
    bridge.start().then(async()=>{
      if(bridge.preview){const result=await bridge.call('show_rollout_trace',bridge.preview.traceId?{traceId:bridge.preview.traceId}:{});apply(result);}
      const list=await bridge.call('list_rollout_traces');if(!active)return;
      if(!received.current)apply({view:'select',...list});setTraces(list.traces);setRootPath(list.defaultRoot);
    }).catch(e=>{if(active){setError(e.message);setLoading(false);}});
    return()=>{active=false;generation.current++;bridge.dispose();clearTimeout(toastTimer.current);};
  },[loadTrace]);
  useEffect(()=>{document.body.toggleAttribute('data-ds-dark-theme',dark);document.documentElement.style.colorScheme=dark?'dark':'light';},[dark]);
  useEffect(()=>{document.documentElement.lang=locale;},[locale]);
  useEffect(()=>{const notice=event=>notify(event.detail);window.addEventListener('rollout-viewer:notice',notice);return()=>window.removeEventListener('rollout-viewer:notice',notice);},[notify]);
  useEffect(()=>{const cleanup=[];installIconSprite({effect:setup=>cleanup.push(setup()),on:()=>{}},undefined);return()=>cleanup.forEach(dispose=>dispose?.());},[]);
  useEffect(()=>()=>disposeImageTransfers(),[]);
  useEffect(()=>{
    if(!data||!live||data.status!=='running')return;
    let cancelled=false,busy=false;
    const traceId=data.trace.id;
    const timer=setInterval(async()=>{
      if(busy||document.hidden)return;busy=true;
      try{
        const delta=await call('get_rollout_delta',{traceId,revision:data.revision});if(cancelled)return;
        if(delta.resync){await loadTrace(traceId);return;}
        if(!delta.unchanged)setData(current=>{
          if(current?.trace.id!==traceId)return current;
          const rows=new Map(current.rows.map(row=>[row.id,row]));for(const row of delta.rows)rows.set(row.id,row);
          return {...current,...delta,rows:[...rows.values()].sort((a,b)=>a.seq-b.seq)};
        });
      }catch(e){if(!cancelled)setError(e.message);}finally{busy=false;}
    },1500);
    return()=>{cancelled=true;clearInterval(timer);};
  },[data?.trace.id,data?.revision,data?.status,live,call,loadTrace]);
  const earlier=useCallback(async()=>{
    if(!data?.hasEarlier||earlierBusy.current)return false;
    earlierBusy.current=true;const ticket=generation.current;
    try{
      const page=await call('get_rollout_overview',{traceId:data.trace.id,beforeSeq:data.beforeSeq,limit:200});
      if(ticket!==generation.current)return false;
      setData(current=>{if(current?.trace.id!==data.trace.id)return current;const rows=new Map(current.rows.map(row=>[row.id,row]));for(const row of page.rows)rows.set(row.id,row);return {...current,rows:[...rows.values()].sort((a,b)=>a.seq-b.seq),hasEarlier:page.hasEarlier,beforeSeq:page.beforeSeq};});
      return page.rows.length>0;
    }catch(e){if(ticket===generation.current)setError(e.message);return false;}finally{earlierBusy.current=false;}
  },[data,call]);
  async function refresh(){try{const list=await call('list_rollout_traces',{refresh:true});setTraces(list.traces);if(data)await loadTrace(data.trace.id);else setError('');}catch(e){setError(e.message);}}
  async function register(){
    if(!directory.trim())return;setAdding(true);setError('');
    try{await call('add_rollout_directory',{path:directory.trim()});const list=await call('list_rollout_traces',{refresh:true});setTraces(list.traces);setDirectory('');notify(text('录制目录已添加','Recording directory added'));}
    catch(e){setError(e.message);}finally{setAdding(false);}
  }
  const stats=data?`${data.rows.length} / ${data.totalRows} ${text('条执行记录','records')} · ${data.requestCount} ${text('次模型请求','requests')} · ${data.toolCount} ${text('次工具执行','tools')}${data.codeCellCount?` · ${data.codeCellCount} ${text('个代码调用','code calls')}`:''}`:'';
  const languages={zh:'中文',en:'English',ja:'日本語',es:'Español',fr:'Français',de:'Deutsch',ru:'Русский',pt:'Português'};
  const directoryForm=<form className="app-directory-form" onSubmit={e=>{e.preventDefault();register();}}>
    <label htmlFor="recording-directory">{text('录制目录','Recording directory')}</label><input id="recording-directory" value={directory} onChange={e=>setDirectory(e.target.value)} placeholder={text('包含 manifest.json 的目录或其父目录','Directory containing manifest.json, or its parent')}/>
    <button type="submit" className="app-button" disabled={adding||!directory.trim()}>{adding?text('正在添加…','Adding…'):text('添加目录','Add directory')}</button>
    <label htmlFor="interface-locale">{text('界面语言','Interface language')}</label><select id="interface-locale" value={locale} onChange={e=>setLocale(e.target.value)}>{supportedLocales.map(value=><option key={value} value={value}>{languages[value]}</option>)}</select>
    {data&&<output className="app-recording-stats" aria-label={text('录制统计','Recording statistics')}>{stats}</output>}
  </form>;
  return <LocaleContext.Provider value={t}><main className={`${view.root} app-frame`} aria-label="Rollout Viewer">
    <header className="app-header"><h1 title={data?.trace.label}>{data?.trace.label||'Rollout Viewer'}</h1><span className="app-status" title={stats} data-status={data?.status}>{data?text(statusNames[data.status]||data.status,{running:'Running',complete:'Complete',error:'Failed',cancelled:'Cancelled'}[data.status]||data.status):text('本地录制','Local recordings')}</span>
      {data&&<button type="button" className="app-button app-live" aria-label={text('跟随录制','Follow recording')} aria-pressed={live} onClick={()=>setLive(!live)} title={text('跟随正在录制的任务','Follow a running recording')}>{text('实时','Live')}</button>}
      <button type="button" className="app-button app-theme" onClick={()=>setDark(!dark)} aria-label={dark?text('切换浅色','Use light theme'):text('切换深色','Use dark theme')}>{dark?text('浅色','Light'):text('深色','Dark')}</button></header>
    <div className="app-source-bar"><span className="app-view-name" aria-current="page">{t('view.trajectory')}</span><select aria-label={text('选择录制任务','Select recording')} value={data?.trace.id||''} onChange={e=>loadTrace(e.target.value)}><option value="" disabled>{text('选择已录制任务…','Select a recording…')}</option>
      {traces.map(trace=><option key={trace.id} value={trace.id}>{timeLabel(trace.startedAt)} · {trace.label}</option>)}</select>
      {data?.threads?.length>1&&<select className="app-agent-select" aria-label={text('筛选代理','Filter agents')} value={thread} onChange={e=>setThread(e.target.value)}><option value="all">{text('全部代理','All agents')}</option>{data.threads.map(agent=><option key={agent.id} value={agent.id}>{agent.label}</option>)}</select>}
      <button type="button" className="app-button" onClick={refresh}>{text('刷新','Refresh')}</button><details className="app-source-settings"><summary aria-label={text('录制设置','Recording settings')}>{text('目录','Directory')}</summary>{directoryForm}</details></div>
    {error&&<Failure error={error} retry={()=>data?loadTrace(data.trace.id):location.reload()}/>}
    {loading?<Skeleton/>:!data?<section className="app-empty"><h2>{text('选择一份录制开始查看','Choose a recording')}</h2><p>{text('在上方选择已录制任务，或通过「目录」添加录制位置。','Select a recording above, or add a recording directory.')}</p>
      <p>{text('官方 rollout-trace 需要在 Codex 启动前开启，现有聊天无法补录。','Enable official rollout-trace before starting Codex. Existing chats cannot be recorded retroactively.')}</p><button type="button" className="app-button" onClick={()=>copy(`CODEX_ROLLOUT_TRACE_ROOT=${quoteShell(rootPath)} codex`)}>{text('复制 CLI 录制命令','Copy CLI recording command')}</button>
      <span>{traces.length?text(`找到 ${traces.length} 份录制`,`${traces.length} recordings found`):text('尚未找到录制','No recordings found')} · {text('数据保存在本机','Stored locally')}</span></section>:<>
      <Trajectory key={`${data.trace.id}:${data.revision.split(':')[0]}`} {...{data,call,earlier,copy,thread,focusCallId}} onFocusApplied={()=>setFocusCallId(null)}/>
    </>}
    <div className={`app-toast ${toast?'visible':''}`} role="status">{toast}</div>
  </main></LocaleContext.Provider>;
}
createRoot(document.getElementById('root')).render(<App/>);
