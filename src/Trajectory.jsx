import React, {useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore} from 'react';
import {TrajectoryTable} from '../vendor/dsh/packages/client/ui-trajectory/src/client/TrajectoryTable.tsx';
import {TrajectoryTimeline} from '../vendor/dsh/packages/client/ui-trajectory/src/client/TrajectoryTimeline.tsx';
import {TrajectoryToolbar} from '../vendor/dsh/packages/client/ui-trajectory/src/client/TrajectoryToolbar.tsx';
import {trajectoryTimelineFocusIndexes} from '../vendor/dsh/packages/client/ui-trajectory/src/client/timeline.ts';
import {useTranslation} from './locale-context.jsx';
import {renderImageSlot as renderSlot,loadImage} from './images.jsx';
import {Failure, Skeleton, RequestContent, readComplete} from './content.jsx';
import view from '../vendor/dsh/packages/client/ui-trajectory/src/client/views.module.css';
import {durationPreference,wrappingPreference} from './preferences.js';

export {t} from './locale.js';
const toggle=(set,key)=>set(current=>{const next=new Set(current);next.has(key)?next.delete(key):next.add(key);return next;});
const toggleAll=(set,ids,collapsed)=>set(current=>{const next=new Set(current);for(const id of ids)collapsed?next.delete(id):next.add(id);return next;});

export default function Trajectory({data,call,earlier,copy,thread,focusCallId,onFocusApplied}) {
  const t=useTranslation();
  const groupOf=cell=>cell.inputHistory?t.text('历史消息（请求输入）','History in request'):cell.cellKey==='compaction'||cell.purpose==='compaction'?t('group.compaction',{seq:cell.seq}):cell.step>0?t('group.step',{step:cell.step}):cell.group;
  const captionOf=cell=>{
    if(cell.kind==='system'&&cell.cellKey==='prompt')return t.text(cell.text,cell.previousPromptDetail?'Instructions and tools updated':'Instructions and tool catalog');
    if(cell.kind==='compacted')return t.text(cell.text,'Context compaction');
    if(cell.kind==='message'&&cell.text==='（仅工具调用）')return `（${t('layout.toolCallOnly')}）`;
    if(['user','context','message'].includes(cell.kind)&&/^(图片|文件) ×/.test(cell.text)){
      const images=cell.sourceBlocks?.filter(block=>block.attachment).length??0,files=cell.sourceBlocks?.filter(block=>block.file).length??0;
      return [images?t('layout.imageCount',{count:images}):'',files?t('layout.fileAttachments',{count:files}):''].filter(Boolean).join(' · ');
    }
    return cell.text;
  };
  const traceId=data.trace.id;
  const [cells,setCells]=useState(new Map()),[requests,setRequests]=useState(new Map());
  const [loading,setLoading]=useState(true),[error,setError]=useState(''),[retry,setRetry]=useState(0);
  const [collapsedTurns,setCollapsedTurns]=useState(new Set()),[collapsedAssistants,setCollapsedAssistants]=useState(new Set()),[collapsedTools,setCollapsedTools]=useState(new Set());
  const duration=useSyncExternalStore(durationPreference.subscribe,durationPreference.getSnapshot);
  const [actualTime,setActualTime]=useState(false);
  const [query,setQuery]=useState(''),[matches,setMatches]=useState(null),[searchBusy,setSearchBusy]=useState(false);
  const [range,setRange]=useState(null),[selectedIndex,setSelectedIndex]=useState(null);
  useEffect(()=>{setRange(null);},[duration,actualTime]);
  const [selection,setSelection]=useState(null),[focus,setFocus]=useState(null);
  const wrapped=useSyncExternalStore(wrappingPreference.subscribe,wrappingPreference.getSnapshot);
  const versions=useRef(new Map()),inflight=useRef(new Map()),requestInflight=useRef(new Set()),live=useRef(true);
  const templates=useRef(new Map()),hydrated=useRef(new Map()),activeRecord=useRef(null);
  const api=useCallback((name,args)=>call(name,{traceId,...args}),[traceId,call]);
  useEffect(()=>{live.current=true;return()=>{live.current=false;};},[]);
  useEffect(()=>{
    let active=true;
    const changed=data.rows.filter(row=>versions.current.get(row.id)!==row.version).map(row=>row.id);
    if(!changed.length){setLoading(false);return;}
    async function refresh(){
      try {
        for(let offset=0;offset<changed.length;offset+=200){
          const page=await api('get_rollout_projection',{rowIds:changed.slice(offset,offset+200)});
          if(!active)return;
          const replaced=new Set(page.rowIds);
          setCells(current=>{
            const next=new Map([...current].filter(([,cell])=>!replaced.has(cell.rowId)));
            for(const cell of page.cells){templates.current.set(cell.recordId,cell);const old=current.get(cell.recordId);next.set(cell.recordId,old?.version===cell.version&&!old.detailsPending?old:cell);}
            return next;
          });
          setRequests(current=>{const next=new Map(current);for(const request of page.requestNumbers)next.set(request.rowId,{...request,detailsPending:true});return next;});
          for(const row of data.rows)if(replaced.has(row.id))versions.current.set(row.id,row.version);
        }
        setError('');
      }catch(e){if(active)setError(e.message);}
      finally{if(active)setLoading(false);}
    }
    refresh();return()=>{active=false;};
  },[api,data.rows,retry]);

  const visibleCells=useMemo(()=>[...cells.values()].filter(cell=>thread==='all'||cell.threadId===thread)
    .sort((a,b)=>a.seq-b.seq||a.slot-b.slot).map((cell,index)=>({...cell,index:index+1,group:groupOf(cell),text:captionOf(cell)})),[cells,thread,t]);
  const turns=useMemo(()=>{
    const sections=new Map();
    for(const cell of visibleCells){
      const key=cell.turn??`between:${cell.rowId}`;
      if(!sections.has(key))sections.set(key,{turn:cell.turn,groups:[],byGroup:new Map()});
      const section=sections.get(key);
      let group=section.byGroup.get(cell.group);
      if(!group){group={title:cell.group,cells:[]};section.byGroup.set(cell.group,group);section.groups.push(group);}
      group.cells.push(cell);
    }
    return [...sections.values()].map(({turn,groups})=>({turn,groups}));
  },[visibleCells]);
  const requestNumbers=useMemo(()=>{const visible=new Set(visibleCells.map(cell=>cell.rowId));return [...requests.values()].filter(request=>visible.has(request.rowId)).sort((a,b)=>a.seq-b.seq).map(request=>({...request,group:groupOf(request)}));},[requests,visibleCells,t]);

  const hydrate=useCallback(async(cell,force=false)=>{
    if(!cell||(!cell.detailsPending&&!force))return;
    const key=`${cell.recordId}:${cell.version}`;
    if(inflight.current.has(key))return inflight.current.get(key);
    const promise=(async()=>{
      try{
        const metadata=await api('get_rollout_cell_detail',{rowId:cell.rowId,cellKey:cell.cellKey});
        const fields=await Promise.all(Object.entries(metadata.fields).map(async([field,info])=>{
          const text=await readComplete(api,'read_rollout_cell_text',{rowId:cell.rowId,cellKey:cell.cellKey,field,version:metadata.cell.version},()=>live.current);
          return [field,info.json&&text!==null?JSON.parse(text):text];
        }));
        if(!live.current)return;
        const complete={...metadata.cell,...Object.fromEntries(fields),detailsPending:false};
        const size=Object.values(metadata.fields).reduce((sum,field)=>sum+field.totalChars*4,0);
        setCells(current=>{
          if(current.get(cell.recordId)?.version!==cell.version)return current;
          const next=new Map(current);next.set(cell.recordId,complete);
          hydrated.current.delete(cell.recordId);hydrated.current.set(cell.recordId,size);
          let total=[...hydrated.current.values()].reduce((sum,value)=>sum+value,0);
          for(const [id,bytes] of hydrated.current){
            if(hydrated.current.size<=20&&total<=16*1024*1024)break;
            if(id===activeRecord.current||id===cell.recordId)continue;
            hydrated.current.delete(id);total-=bytes;
            if(templates.current.has(id))next.set(id,templates.current.get(id));
          }
          return next;
        });
      }catch(e){
        if(live.current)setCells(current=>{if(current.get(cell.recordId)?.version!==cell.version)return current;const next=new Map(current);next.set(cell.recordId,{...cell,detailsError:e.message});return next;});
      }finally{inflight.current.delete(key);}
    })();
    inflight.current.set(key,promise);return promise;
  },[api]);
  const selectIndex=useCallback(index=>{
    setSelectedIndex(index);
    const cell=visibleCells.find(value=>value.index===index);activeRecord.current=cell?.recordId??null;if(cell)hydrate(cell);
  },[visibleCells,hydrate]);
  // A completion changes the selected record's version without changing its index.
  useEffect(()=>{const cell=visibleCells.find(value=>value.index===selectedIndex);if(cell?.detailsPending&&!cell.detailsError)hydrate(cell);},[visibleCells,selectedIndex,hydrate]);
  const selectRequest=useCallback(request=>{
    const key=`${request?.rowId}:${request?.version}`;
    if(!request?.detailsPending||requestInflight.current.has(key))return;
    requestInflight.current.add(key);
    api('get_rollout_request_info',{rowId:request.rowId}).then(value=>{
      if(live.current)setRequests(current=>{if(current.get(request.rowId)?.version!==request.version)return current;const next=new Map(current);next.set(request.rowId,{...value.request,detailsPending:false});return next;});
    }).catch(e=>{if(live.current)setRequests(current=>{if(current.get(request.rowId)?.version!==request.version)return current;const next=new Map(current);next.set(request.rowId,{...request,detailsError:e.message});return next;});})
      .finally(()=>requestInflight.current.delete(key));
  },[api]);

  const rowIds=useMemo(()=>[...new Set(visibleCells.map(cell=>cell.rowId))],[visibleCells]);
  const rowKey=rowIds.join('|');
  useEffect(()=>{
    if(!query.trim()){setMatches(null);setSearchBusy(false);return;}
    let active=true;setSearchBusy(true);
    const timer=setTimeout(async()=>{
      try{
        const found=[];
        for(let offset=0;offset<rowIds.length;offset+=200){const result=await api('search_rollout_cells',{query,rowIds:rowIds.slice(offset,offset+200),locale:t.locale});if(!active)return;found.push(...result.matches);}
        if(active){setMatches(new Set(found));setError('');}
      }catch(e){if(active)setError(e.message);}finally{if(active)setSearchBusy(false);}
    },200);
    return()=>{active=false;clearTimeout(timer);};
  },[api,query,rowKey,data.revision,retry,t]);
  const searchIndexes=useMemo(()=>matches===null?null:new Set(visibleCells.filter(cell=>matches.has(cell.recordId)).map(cell=>cell.index)),[visibleCells,matches]);
  const mode=duration?(actualTime?'actual':'duration'):(actualTime?'time':'sequence');
  const timelineFocus=useMemo(()=>range===null?null:trajectoryTimelineFocusIndexes(turns,range,mode),[turns,range,mode]);
  const turnIds=turns.filter(turn=>turn.turn!==null&&turn.groups.flatMap(group=>group.cells).filter(cell=>cell.kind!=='system'&&!cell.requestOnly).length>1).map(turn=>turn.turn);
  const assistantIds=visibleCells.filter((cell,index)=>cell.kind==='message'&&['tool','subtool'].includes(visibleCells[index+1]?.kind)).map(cell=>cell.recordId);
  const toolIds=visibleCells.filter((cell,index)=>cell.kind==='tool'&&visibleCells[index+1]?.kind==='subtool').map(cell=>cell.recordId);
  const allTurns=turnIds.length>0&&turnIds.every(id=>collapsedTurns.has(id));
  const allAssistants=assistantIds.length>0&&assistantIds.every(id=>collapsedAssistants.has(id));
  const allTools=toolIds.length>0&&toolIds.every(id=>collapsedTools.has(id));
  const wrapping=useMemo(()=>({getDefault:wrappingPreference.getSnapshot,setDefault:wrappingPreference.set,label:t('record.wrapLines')}),[wrapped,t]);
  const watchToolResult=useCallback((seq,receive)=>{
    let active=true;
    const row=data.rows.find(value=>value.seq===seq);
    if(row)readComplete(api,'read_rollout_text',{rowId:row.id,section:'raw_result'},()=>active).then(text=>{
      if(!active)return;
      if(text===null){receive(undefined);return;}
      try{receive(JSON.parse(text));}catch{receive(text);}
    }).catch(()=>{if(active)receive(undefined);});
    return()=>{active=false;receive(undefined);};
  },[api,data.rows]);
  const requestContent=useCallback((request,tab)=><RequestContent key={`${request.rowId}:${request.version}:${tab}`} {...{traceId,request,tab,call,copy}}/>,[traceId,call,copy]);
  const renderPending=useCallback(record=>record.detailsError
    ?<Failure error={record.detailsError} retry={()=>record.recordId?hydrate(record,true):selectRequest({...record,detailsError:undefined})}/>
    :<Skeleton/>,[hydrate,selectRequest]);

  if(loading)return <Skeleton/>;
  return <>
    {error&&<Failure error={error} retry={()=>setRetry(value=>value+1)}/>}
    <TrajectoryToolbar actualDuration={duration} onActualDurationChange={value=>{setRange(null);durationPreference.set(value);}} actualTime={actualTime} onActualTimeChange={value=>{setRange(null);setActualTime(value);}}
      allTurnsCollapsed={allTurns} onToggleAllTurns={()=>toggleAll(setCollapsedTurns,turnIds,allTurns)}
      allAssistantsCollapsed={allAssistants} onToggleAllAssistants={()=>toggleAll(setCollapsedAssistants,assistantIds,allAssistants)}
      allSubCallsCollapsed={allTools} showSubCalls={toolIds.length>0} onToggleAllSubCalls={()=>toggleAll(setCollapsedTools,toolIds,allTools)} searchQuery={query} onSearchQueryChange={setQuery} t={t}/>
    <TrajectoryTimeline turns={turns} mode={mode} range={range} onRangeChange={setRange} hasEarlierRecords={data.hasEarlier}
      onLoadEarlier={earlier} selectedIndex={selectedIndex} searchMatchIndexes={searchIndexes} onRecordSelect={index=>{setRange(null);setSelection({index});}}
      onRecordFocus={index=>setFocus({index})} t={t}/>
    {query&&<div className="app-search-status" role="status">{searchBusy?t.text('正在搜索已加载记录的完整内容…','Searching the full content of loaded records…'):t.text(`${matches?.size||0} 条匹配 · 搜索已加载记录`,`${matches?.size||0} matches in loaded records`)}</div>}
    <div className={`${view.ledger} app-ledger-region`}>
      <TrajectoryTable turns={turns} requestNumbers={requestNumbers} t={t} renderSlot={renderSlot} loadImage={loadImage} watchToolResult={watchToolResult}
        inspectCallId={focusCallId} onInspectApplied={onFocusApplied}
        stringWrapping={wrapping} collapsedTurns={collapsedTurns} onToggleTurn={id=>toggle(setCollapsedTurns,id)}
        collapsedAssistants={collapsedAssistants} onToggleAssistant={id=>toggle(setCollapsedAssistants,id)}
        collapsedTools={collapsedTools} onToggleTool={id=>toggle(setCollapsedTools,id)}
        timelineFocusIndexes={timelineFocus} searchMatchIndexes={searchIndexes} onSelectedIndexChange={selectIndex}
        onRecordSelect={index=>{if(timelineFocus&&!timelineFocus.has(index))setRange(null);}}
        recordSelection={selection} recordFocus={focus} hasOlderRecords={data.hasEarlier} onLoadOlder={earlier}
        historyStartSeq={data.rows[0]?.seq} onClearSelection={()=>{setRange(null);setSelection(null);setFocus(null);}}
        onRequestSelected={selectRequest} renderRequestContent={requestContent} renderPending={renderPending}/>
    </div>
  </>;
}
