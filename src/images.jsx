import React from 'react';
import {ImageGallery} from '../vendor/dsh/packages/client/ui-attachment/src/MessageImage.tsx';
import {FileTransfers} from '../vendor/dsh/packages/client/ui-file-drag/src/client/transfers.ts';

// Labels match the pinned conversation image dictionary. Only the byte loader
// and browser drag transport differ from DSH's Gateway-backed attachment store.
const labels={image:'图片',open:'查看原图',openNamed:label=>`${label}，点击查看原图`,
  loading:'图片加载中…',loadFailed:'图片加载失败，点击重试',lightbox:{dialog:'原图预览',close:'关闭原图预览'}};
const cache=new Map();let cachedBytes=0;
export const loadImage=attachment=>{
  const id=attachment.attachmentId,existing=cache.get(id);
  if(existing)return existing.promise;
  const entry={url:null,size:0,promise:null};
  entry.promise=Promise.resolve().then(async()=>{
    const url=attachment.recordedUrl;
    if(typeof url!=='string'||!url.startsWith('data:image/'))throw new Error('图片内容未保存在录制中');
    const probe=new Image();probe.src=url;await probe.decode();
    entry.url=url;entry.size=url.length*2;cachedBytes+=entry.size;
    for(const [key,item] of cache){
      if(cache.size<=64&&cachedBytes<=16*1024*1024)break;
      cache.delete(key);cachedBytes-=item.size;
    }
    return url;
  }).catch(error=>{if(cache.get(id)===entry)cache.delete(id);throw error;});
  cache.set(id,entry);return entry.promise;
};
loadImage.peek=attachment=>cache.get(attachment.attachmentId)?.url??undefined;

const reportDragFailure=()=>window.dispatchEvent(new CustomEvent('rollout-viewer:notice',{detail:'图片暂时无法拖出，请重试。'}));
let transfers;
const fileDrag={
  async prepare(source,signal){
    if(signal.aborted)throw new DOMException('Aborted','AbortError');
    let blob=source.blob;
    if(!blob){
      if(!source.url.startsWith('data:image/'))throw new Error('没有记录原图内容');
      const comma=source.url.indexOf(','),header=source.url.slice(0,comma),encoded=source.url.slice(comma+1);
      const bytes=header.includes(';base64')?Uint8Array.from(atob(encoded),value=>value.charCodeAt(0)):new TextEncoder().encode(decodeURIComponent(encoded));
      blob=new Blob([bytes],{type:header.slice(5).split(';')[0]});
    }
    transfers??=new FileTransfers(undefined,reportDragFailure);
    return transfers.prepare({...source,kind:'blob',blob,mediaType:source.mediaType||blob.type},signal);
  },
  reportFailure:reportDragFailure,
};
export function disposeImageTransfers(){transfers?.dispose();transfers=undefined;}
const getTriggerProps=()=>({});
export function renderImageSlot(_,props){return <ImageGallery {...props} load={loadImage} labels={labels} fileDrag={fileDrag} getTriggerProps={getTriggerProps}/>;}
