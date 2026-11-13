import React,{useState,useEffect,useRef,useCallback} from 'react';
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

const statusNames={running:'进行中',complete:'已结束',error:'失败',cancelled:'已取消'};
const timeLabel=value=>typeof value==='number'?new Date(value).toLocaleString(undefined,{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}):'时间未知';
const quoteShell=value=>`'${String(value).replaceAll("'", "'\"'\"'")}'`;

function App(){
  const host=useRef(),received=useRef(false),generation=useRef(0),earlierBusy=useRef(false),toastTimer=useRef();
  const [data,setData]=useState(null),[traces,setTraces]=useState([]),[loading,setLoading]=useState(true),[error,setError]=useState('');
  const [thread,setThread]=useState('all'),[dark,setDark]=useState(false),[live,setLive]=useState(true),[toast,setToast]=useState('');
  const [directory,setDirectory]=useState(''),[adding,setAdding]=useState(false),[rootPath,setRootPath]=useState('');
  const call=useCallback((name,args={})=>host.current?host.current.call(name,args):Promise.reject(new Error('面板正在连接。')),[]);
  const notify=useCallback(text=>{setToast(text);clearTimeout(toastTimer.current);toastTimer.current=setTimeout(()=>setToast(''),2200);},[]);
  const copy=useCallback(async text=>{try{await navigator.clipboard.writeText(text);notify('已复制完整内容');}catch{notify('复制失败，请选择文本复制');}},[notify]);
  const loadTrace=useCallback(async id=>{
    if(!id)return;
    const ticket=++generation.current;setLoading(true);setError('');
    try{const value=await call('get_rollout_overview',{traceId:id});if(ticket!==generation.current)return;setData(value);setThread('all');setLoading(false);}
    catch(e){if(ticket===generation.current){setError(e.message);setLoading(false);}}
  },[call]);
  useEffect(()=>{
    let active=true;
    function apply(value){
      if(!active)return;received.current=true;
      if(value.view==='open'){loadTrace(value.trace.id);return;}
      if(value.rows){generation.current++;setData(value);setThread('all');setLoading(false);setError('');return;}
      if(value.view==='select'){setTraces(value.traces||[]);setRootPath(value.defaultRoot||'');setData(null);setLoading(false);}
    }
    const bridge=createHost({onResult:result=>apply(result.structuredContent||result),onContext:context=>{if(active&&context.theme)setDark(context.theme==='dark');},onError:e=>{if(active){setError(e.message);setLoading(false);}}});
    host.current=bridge;
    bridge.start().then(async()=>{
      if(bridge.preview){const result=await bridge.call('show_rollout_trace',bridge.preview.traceId?{traceId:bridge.preview.traceId}:{});apply(result);}
      const list=await bridge.call('list_rollout_traces');if(!active)return;
      if(!received.current)apply({view:'select',...list});setTraces(list.traces);setRootPath(list.defaultRoot);
    }).catch(e=>{if(active){setError(e.message);setLoading(false);}});
    return()=>{active=false;generation.current++;bridge.dispose();clearTimeout(toastTimer.current);};
  },[loadTrace]);
  useEffect(()=>{document.body.toggleAttribute('data-ds-dark-theme',dark);document.documentElement.style.colorScheme=dark?'dark':'light';},[dark]);
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
    try{await call('add_rollout_directory',{path:directory.trim()});const list=await call('list_rollout_traces',{refresh:true});setTraces(list.traces);setDirectory('');notify('录制目录已添加');}
    catch(e){setError(e.message);}finally{setAdding(false);}
  }
  const directoryForm=<form className="app-directory-form" onSubmit={e=>{e.preventDefault();register();}}>
    <label htmlFor="recording-directory">录制目录</label><input id="recording-directory" value={directory} onChange={e=>setDirectory(e.target.value)} placeholder="包含 manifest.json 的目录或其父目录"/>
    <button type="submit" className="app-button" disabled={adding||!directory.trim()}>{adding?'正在添加…':'添加目录'}</button>
  </form>;
  return <main className={`${view.root} app-frame`} aria-label="Rollout Viewer">
    <header className="app-header"><h1>Rollout Viewer</h1><span className="app-status" data-status={data?.status}>{data?statusNames[data.status]||data.status:'本地录制'}</span>
      <button type="button" className="app-button app-theme" onClick={()=>setDark(!dark)} aria-label={dark?'切换浅色':'切换深色'}>{dark?'浅色':'深色'}</button></header>
    <div className="app-source-bar"><select aria-label="选择录制任务" value={data?.trace.id||''} onChange={e=>loadTrace(e.target.value)}><option value="" disabled>选择已录制任务…</option>
      {traces.map(trace=><option key={trace.id} value={trace.id}>{timeLabel(trace.startedAt)} · {trace.label}</option>)}</select>
      <button type="button" className="app-button" onClick={refresh}>刷新</button><details className="app-source-settings"><summary aria-label="录制设置">目录</summary>{directoryForm}</details></div>
    {error&&<Failure error={error} retry={()=>data?loadTrace(data.trace.id):location.reload()}/>}
    {loading?<Skeleton/>:!data?<section className="app-empty"><h2>选择一份录制开始查看</h2><p>在上方选择已录制任务，或通过「目录」添加录制位置。</p>
      <p>官方 rollout-trace 需要在 Codex 启动前开启，现有聊天无法补录。</p><button type="button" className="app-button" onClick={()=>copy(`CODEX_ROLLOUT_TRACE_ROOT=${quoteShell(rootPath)} codex`)}>复制 CLI 录制命令</button>
      <span>{traces.length?`找到 ${traces.length} 份录制`:'尚未找到录制'} · 数据保存在本机</span></section>:<>
      <div className="app-session-bar"><span title={data.trace.threadId}>{data.trace.label}</span>
        {data.threads?.length>1&&<select aria-label="筛选代理" value={thread} onChange={e=>setThread(e.target.value)}><option value="all">全部代理</option>{data.threads.map(agent=><option key={agent.id} value={agent.id}>{agent.label}</option>)}</select>}
        <button type="button" className="app-button" aria-pressed={live} onClick={()=>setLive(!live)} title="跟随正在录制的任务">{live?'实时已开':'实时已关'}</button></div>
      <Trajectory key={`${data.trace.id}:${data.revision.split(':')[0]}`} {...{data,call,earlier,copy,thread}}/>
      <footer className="app-footer"><span>{data.rows.length} / {data.totalRows} 条执行记录</span><span>{data.requestCount} 次模型请求 · {data.toolCount} 次工具执行{data.codeCellCount>0&&` · ${data.codeCellCount} 个代码调用`}</span></footer>
    </>}
    <div className={`app-toast ${toast?'visible':''}`} role="status">{toast}</div>
  </main>;
}
createRoot(document.getElementById('root')).render(<App/>);
