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
import {IconEllipsisOutlineRegular} from '../vendor/dsh/packages/client/ui-primitives/src/icons/index.tsx';

const statusNames={running:'录制中',complete:'已结束',error:'失败',cancelled:'已取消'};
const timeLabel=value=>typeof value==='number'?new Date(value).toLocaleString(undefined,{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}):'时间未知';
const quoteShell=value=>`'${String(value).replaceAll("'", "'\"'\"'")}'`;

function App(){
  const host=useRef(),received=useRef(false),generation=useRef(0),earlierBusy=useRef(false),toastTimer=useRef();
  const menuRoot=useRef(null),menuButton=useRef(null);
  const [menuOpen,setMenuOpen]=useState(false);
  const [data,setData]=useState(null),[traces,setTraces]=useState([]),[loading,setLoading]=useState(true),[error,setError]=useState('');
  const [thread,setThread]=useState('all'),[dark,setDark]=useState(false),[live,setLive]=useState(true),[toast,setToast]=useState('');
  const [directory,setDirectory]=useState(''),[adding,setAdding]=useState(false),[rootPath,setRootPath]=useState('');
  const [focusCallId,setFocusCallId]=useState(null);
  const [selectionInfo,setSelectionInfo]=useState(null),[catalogInfo,setCatalogInfo]=useState(null);
  const [followingThread,setFollowingThread]=useState(null),[connected,setConnected]=useState(false);
  const latestData=useRef(null);latestData.current=data;
  const [locale,setLocale]=useState('zh');
  const t=useMemo(()=>translatorFor(locale),[locale]);
  const text=t.text;
  const closeMenu=useCallback(()=>{setMenuOpen(false);menuButton.current?.focus();},[]);
  useEffect(()=>{
    if(!menuOpen)return;
    const outside=event=>{if(!menuRoot.current?.contains(event.target))setMenuOpen(false);};
    const escape=event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();closeMenu();}};
    document.addEventListener('click',outside);
    document.addEventListener('focusin',outside);
    document.addEventListener('keydown',escape,true);
    menuRoot.current?.querySelector('[data-menu-initial-focus]')?.focus();
    return()=>{document.removeEventListener('click',outside);document.removeEventListener('focusin',outside);document.removeEventListener('keydown',escape,true);};
  },[menuOpen,closeMenu]);
  const call=useCallback((name,args={})=>host.current?host.current.call(name,args):Promise.reject(new Error('面板正在连接。')),[]);
  const notify=useCallback(text=>{setToast(text);clearTimeout(toastTimer.current);toastTimer.current=setTimeout(()=>setToast(''),2200);},[]);
  const copy=useCallback(async value=>{try{await navigator.clipboard.writeText(value);notify(text('已复制完整内容','Complete content copied'));}catch{notify(text('复制失败，请选择文本复制','Copy failed; select the text to copy'));}},[notify,text]);
  const loadTrace=useCallback(async(id,focus=null,{quiet=false,preserve=false}={})=>{
    if(!id)return;
    const ticket=++generation.current;if(!quiet)setLoading(true);setError('');
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
      if(ticket!==generation.current)return;setData(value);if(!preserve){setThread('all');setFocusCallId(focus);}setLoading(false);
    }
    catch(e){if(ticket===generation.current){setError(e.message);setLoading(false);}}
  },[call]);
  const applyResult=useCallback(value=>{
    if(!value||!['open','trace','select'].includes(value.view))return;
    received.current=true;
    setFollowingThread(value.currentThreadId||null);
    if(value.view==='open'){
      if(value.currentThreadId)setSelectionInfo({currentThreadId:value.currentThreadId});
      loadTrace(value.trace.id,value.focusCallId||null);return;
    }
    if(value.view==='trace'&&Array.isArray(value.rows)){
      setSelectionInfo(value.currentThreadId?{currentThreadId:value.currentThreadId}:null);
      // A delayed host snapshot may predate the data already loaded by this UI connection.
      if(latestData.current?.trace.id===value.trace.id){loadTrace(value.trace.id,null,{quiet:true,preserve:true});return;}
      generation.current++;setData(value);setThread('all');setFocusCallId(null);setLoading(false);setError('');return;
    }
    if(value.view==='select'){
      generation.current++;setSelectionInfo(value);setCatalogInfo(value);setTraces(value.traces||[]);setRootPath(value.defaultRoot||'');setData(null);setFocusCallId(null);setThread('all');setLoading(false);setError('');
    }
  },[loadTrace]);
  useEffect(()=>{
    let active=true;
    const apply=value=>{if(active)applyResult(value);};
    const bridge=createHost({onResult:result=>apply(result.structuredContent||result),onContext:context=>{if(!active)return;if(context.theme)setDark(context.theme==='dark');if(context.locale)setLocale(normalizeLocale(context.locale));},onError:e=>{if(active){setError(e.message);setLoading(false);}}});
    host.current=bridge;
    bridge.start().then(async()=>{
      if(bridge.preview){const result=await bridge.call('show_rollout_trace',bridge.preview.traceId?{traceId:bridge.preview.traceId}:{});apply(result);}
      const list=await bridge.call('list_rollout_traces');if(!active)return;
      if(!received.current)apply({view:'select',...list});setTraces(list.traces);setRootPath(list.defaultRoot);setCatalogInfo(list);setConnected(true);
    }).catch(e=>{if(active){setError(e.message);setLoading(false);}});
    return()=>{active=false;generation.current++;bridge.dispose();clearTimeout(toastTimer.current);};
  },[applyResult]);
  useEffect(()=>{document.body.toggleAttribute('data-ds-dark-theme',dark);document.documentElement.style.colorScheme=dark?'dark':'light';},[dark]);
  useEffect(()=>{document.documentElement.lang=locale;},[locale]);
  useEffect(()=>{const notice=event=>notify(event.detail);window.addEventListener('rollout-viewer:notice',notice);return()=>window.removeEventListener('rollout-viewer:notice',notice);},[notify]);
  useEffect(()=>{const cleanup=[];installIconSprite({effect:setup=>cleanup.push(setup()),on:()=>{}},undefined);return()=>cleanup.forEach(dispose=>dispose?.());},[]);
  useEffect(()=>()=>disposeImageTransfers(),[]);
  useEffect(()=>{
    if(!connected||!live||loading)return;
    let cancelled=false,busy=false;
    async function poll(){
      if(busy||document.hidden)return;busy=true;
      const current=latestData.current,ticket=generation.current;
      const stale=()=>cancelled||ticket!==generation.current;
      try{
        if(!current){const result=await call('open_rollout_viewer');if(!stale())applyResult(result);return;}
        const traceId=current.trace.id;
        if(followingThread){
          const resolved=await call('get_rollout_binding',{threadId:followingThread});if(stale())return;
          const match=resolved.currentThreadId===followingThread?resolved.trace:null;
          if(match&&match.id!==traceId){
            setTraces(current=>[match,...current.filter(trace=>trace.id!==match.id)]);
            await loadTrace(match.id,null,{quiet:true});return;
          }
        }
        const delta=await call('get_rollout_delta',{traceId,revision:current.revision});if(stale())return;
        if(delta.resync){await loadTrace(traceId,null,{quiet:true,preserve:true});return;}
        if(!delta.unchanged)setData(current=>{
          if(current?.trace.id!==traceId)return current;
          const rows=new Map(current.rows.map(row=>[row.id,row]));for(const row of delta.rows)rows.set(row.id,row);
          return {...current,...delta,rows:[...rows.values()].sort((a,b)=>a.seq-b.seq)};
        });
      }catch(e){if(!stale())setError(e.message);}finally{busy=false;}
    }
    const timer=setInterval(poll,1500);
    document.addEventListener('visibilitychange',poll);poll();
    return()=>{cancelled=true;clearInterval(timer);document.removeEventListener('visibilitychange',poll);};
  },[connected,loading,data?.trace.id,followingThread,live,call,loadTrace,applyResult]);
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
  async function refresh(){try{
    const list=await call('list_rollout_traces',{refresh:true});setTraces(list.traces);setCatalogInfo(list);
    if(followingThread){
      const resolved=await call('get_rollout_binding',{threadId:followingThread});
      const match=resolved.currentThreadId===followingThread?resolved.trace:null;
      if(match)await loadTrace(match.id,null,{quiet:!!data,preserve:match.id===data?.trace.id});
      else if(!data)applyResult(await call('open_rollout_viewer'));
    }
    else if(data)await loadTrace(data.trace.id,null,{quiet:true,preserve:true});
    else if(selectionInfo?.currentThreadId){
      const match=list.traces.find(trace=>trace.threadId===selectionInfo.currentThreadId);
      if(match)await loadTrace(match.id);
      else{const issue=list.issues?.find(item=>item.threadId===selectionInfo.currentThreadId);setSelectionInfo(current=>({...current,unavailableReason:issue?.message}));setError('');}
    }else setError('');
  }catch(e){setError(e.message);}}
  async function returnCurrent(){
    const ticket=++generation.current;
    try{const result=await call('open_rollout_viewer');if(ticket===generation.current){applyResult(result);closeMenu();}}
    catch(e){if(ticket===generation.current)setError(e.message);}
  }
  async function register(){
    if(!directory.trim())return;setAdding(true);setError('');
    try{await call('add_rollout_directory',{path:directory.trim()});const list=await call('list_rollout_traces',{refresh:true});setTraces(list.traces);setCatalogInfo(list);setDirectory('');notify(text('录制目录已添加','Recording directory added'));}
    catch(e){setError(e.message);}finally{setAdding(false);}
  }
  const stats=data?`${data.rows.length} / ${data.totalRows} ${text('条执行记录','records')} · ${data.requestCount} ${text('次模型请求','requests')} · ${data.toolCount} ${text('次工具执行','tools')}${data.codeCellCount?` · ${data.codeCellCount} ${text('个代码调用','code calls')}`:''}`:'';
  const traceLabel=data?.trace.isThreadAggregate?text('当前聊天','This chat'):data?.trace.label;
  const languages={zh:'中文',en:'English',ja:'日本語',es:'Español',fr:'Français',de:'Deutsch',ru:'Русский',pt:'Português'};
  const directoryForm=<form className="app-directory-form" onSubmit={e=>{e.preventDefault();register();}}>
    <label htmlFor="recording-directory">{text('录制目录','Recording directory')}</label><input id="recording-directory" value={directory} onChange={e=>setDirectory(e.target.value)} placeholder={text('包含 manifest.json 的目录或其父目录','Directory containing manifest.json, or its parent')}/>
    <button type="submit" className="app-button" disabled={adding||!directory.trim()}>{adding?text('正在添加…','Adding…'):text('添加目录','Add directory')}</button>
    <label htmlFor="interface-locale">{text('界面语言','Interface language')}</label><select id="interface-locale" value={locale} onChange={e=>setLocale(e.target.value)}>{supportedLocales.map(value=><option key={value} value={value}>{languages[value]}</option>)}</select>
    {data&&<output className="app-recording-stats" aria-label={text('录制统计','Recording statistics')}>{stats}</output>}
    {catalogInfo?.unreadableCount>0&&<p className="app-note">{text(`${catalogInfo.unreadableCount} 份录制无法读取：`,`${catalogInfo.unreadableCount} recordings could not be read: `)}{catalogInfo.issues?.map(issue=>issue.message).filter((value,index,list)=>list.indexOf(value)===index).join(' · ')}</p>}
  </form>;
  return <LocaleContext.Provider value={t}><main className={`${view.root} app-frame`} aria-label="Rollout Viewer">
    <header className="app-source-bar">
      <h1 className="app-view-name" aria-current="page">{t('view.trajectory')}</h1>
      <div className="app-source-settings" ref={menuRoot}>
        <button ref={menuButton} type="button" className="app-icon app-more" aria-label={text('更多轨迹操作','More trajectory actions')} title={text('更多轨迹操作','More trajectory actions')} aria-haspopup="dialog" aria-expanded={menuOpen} aria-controls="trajectory-actions" onClick={()=>setMenuOpen(!menuOpen)}><IconEllipsisOutlineRegular size={16}/></button>
        {menuOpen&&<section id="trajectory-actions" className="app-source-menu" role="dialog" aria-labelledby="trajectory-actions-title">
          <div className="app-menu-heading"><h2 id="trajectory-actions-title">{text('轨迹操作','Trajectory actions')}</h2><button type="button" className="app-icon" aria-label={text('关闭轨迹操作','Close trajectory actions')} onClick={closeMenu}>×</button></div>
          <div className="app-recording-title"><strong title={traceLabel}>{traceLabel||'Rollout Viewer'}</strong><span className="app-status" title={stats} data-status={data?.status}>{data?text(statusNames[data.status]||data.status,{running:'Recording',complete:'Complete',error:'Failed',cancelled:'Cancelled'}[data.status]||data.status):text('本地录制','Local recordings')}</span></div>
          <div className="app-recording-picker"><label htmlFor="recording-select">{text('选择录制任务','Select recording')}</label><select id="recording-select" data-menu-initial-focus="" value={data?.trace.id||''} onChange={e=>{setFollowingThread(null);loadTrace(e.target.value);closeMenu();}}><option value="" disabled>{text('选择已录制任务…','Select a recording…')}</option>
            {data?.trace.isThreadAggregate&&<option value={data.trace.id}>{text('当前聊天 · 全部录制','This chat · All recordings')}{` (${data.trace.recordingCount})`}</option>}
            {traces.map(trace=><option key={trace.id} value={trace.id}>{timeLabel(trace.startedAt)} · {trace.label}</option>)}</select>
            {data?.threads?.length>1&&<><label htmlFor="recording-agent">{text('筛选代理','Filter agents')}</label><select id="recording-agent" value={thread} onChange={e=>{setThread(e.target.value);closeMenu();}}><option value="all">{text('全部代理','All agents')}</option>{data.threads.map(agent=><option key={agent.id} value={agent.id}>{agent.label}</option>)}</select></>}
          </div>
          <div className="app-recording-actions">
            {!followingThread&&selectionInfo?.currentThreadId&&<button type="button" className="app-button" onClick={returnCurrent}>{text('返回当前聊天','Return to this chat')}</button>}
            <button type="button" className="app-button" onClick={refresh}>{text('刷新','Refresh')}</button>
            {data&&<button type="button" className="app-button" aria-label={text('跟随录制','Follow recording')} aria-pressed={live} onClick={()=>setLive(!live)} title={text('跟随正在录制的任务','Follow a running recording')}>{text('实时','Live')}</button>}
            <button type="button" className="app-button" onClick={()=>setDark(!dark)} aria-label={dark?text('切换浅色','Use light theme'):text('切换深色','Use dark theme')}>{dark?text('浅色','Light'):text('深色','Dark')}</button>
          </div>
          {directoryForm}
          <small className="app-recording-stats" aria-label={text('界面版本','Interface version')}>Rollout Viewer 0.2.14</small>
          <small className="app-recording-stats" aria-label={text('后台版本','Reader version')}>{text('后台','Reader')} {catalogInfo?.readerVersion||text('未报告','Not reported')}</small>
          {error&&<p className="app-menu-error" role="alert">{error}</p>}
        </section>}
      </div>
    </header>
    {error&&!menuOpen&&<Failure error={error} retry={()=>data?loadTrace(data.trace.id):location.reload()}/>}
    {loading?<Skeleton/>:!data?<section className="app-empty"><h2>{selectionInfo?.unavailableReason?text('当前聊天的录制无法读取','Unable to read this chat recording'):selectionInfo?.currentThreadId?text('当前聊天暂无可读取轨迹','No readable recording for this chat'):text('选择一份录制开始查看','Choose a recording')}</h2>
      {selectionInfo?.unavailableReason?<p role="alert">{selectionInfo.unavailableReason}</p>:<p>{text('打开「···」选择已录制任务，或添加录制目录。','Open “···” to select a recording or add a recording directory.')}</p>}
      {catalogInfo?.recordingConfigured?<p>{text('录制路径已配置。在「···」中点击「刷新」重新匹配当前聊天；已经发生的请求无法补录。','The recording path is configured. Open “···” and refresh to match this chat again; past requests cannot be recorded retroactively.')}</p>:<>
        <p>{text('需要在录制引擎启动前开启官方 rollout-trace；已经发生的请求无法补录。','Enable official rollout-trace before starting the recording engine; past requests cannot be recorded retroactively.')}</p>
        <button type="button" className="app-button" onClick={()=>copy(!host.current?.preview&&catalogInfo?.platform==='darwin'?`launchctl setenv CODEX_ROLLOUT_TRACE_ROOT ${quoteShell(rootPath)}`:`CODEX_ROLLOUT_TRACE_ROOT=${quoteShell(rootPath)} codex`)}>{!host.current?.preview&&catalogInfo?.platform==='darwin'?text('复制桌面录制配置命令','Copy desktop recording setup'):text('复制 CLI 录制命令','Copy CLI recording command')}</button>
      </>}
      <span>{traces.length?text(`找到 ${traces.length} 份可读取录制`,`${traces.length} readable recordings found`):text('尚未找到可读取录制','No readable recordings found')}{catalogInfo?.unreadableCount?text(` · ${catalogInfo.unreadableCount} 份无法读取`,` · ${catalogInfo.unreadableCount} unreadable`):''} · {text('数据保存在本机','Stored locally')}</span></section>:<>
      <Trajectory key={`${data.trace.id}:${data.revision.split(':')[0]}`} {...{data,call,earlier,copy,thread,focusCallId}} onFocusApplied={()=>setFocusCallId(null)}/>
    </>}
    <div className={`app-toast ${toast?'visible':''}`} role="status">{toast}</div>
  </main></LocaleContext.Provider>;
}
createRoot(document.getElementById('root')).render(<App/>);
