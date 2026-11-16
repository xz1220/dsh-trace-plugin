// Deterministic vector and PNG exports. No additional build dependencies.
import {writeFile, mkdir} from 'node:fs/promises';
import {deflateSync} from 'node:zlib';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const output=path.join(root,'plugins/codex-dsh-trace/assets');
const themes={
  light:{tile:'#181C1B',ink:'#F4F7F6',accent:'#64DFC2'},
  dark:{tile:'#F0F5F3',ink:'#18231F',accent:'#087C65'},
};
const route='M18 16V26A6 6 0 0 0 24 32H40A6 6 0 0 1 46 38V48';
function svg(theme){
  const {tile,ink,accent}=themes[theme];
  return `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64" fill="none" role="img" aria-labelledby="title desc">
  <title id="title">Codex Trace</title>
  <desc id="desc">Three execution nodes connected by a continuous path, ending in a highlighted node.</desc>
  <rect x="2" y="2" width="60" height="60" rx="14" fill="${tile}"/>
  <path d="${route}" stroke="${ink}" stroke-width="4.5" stroke-linecap="round"/>
  <circle cx="18" cy="16" r="4.5" fill="${ink}"/>
  <circle cx="32" cy="32" r="4.5" fill="${ink}"/>
  <circle cx="46" cy="48" r="5.5" fill="${accent}"/>
</svg>
`;
}
const rgba=hex=>[1,3,5].map(offset=>parseInt(hex.slice(offset,offset+2),16));
const distance=(x,y,a,b,c,d)=>{
  const t=Math.max(0,Math.min(1,((x-a)*(c-a)+(y-b)*(d-b))/((c-a)**2+(d-b)**2)));
  return Math.hypot(x-a-t*(c-a),y-b-t*(d-b));
};
function onRoute(x,y){
  const firstArc=x<=24&&y>=26?Math.abs(Math.hypot(x-24,y-26)-6):Infinity;
  const secondArc=x>=40&&y<=38?Math.abs(Math.hypot(x-40,y-38)-6):Infinity;
  return Math.min(distance(x,y,18,16,18,26),distance(x,y,24,32,40,32),
    distance(x,y,46,38,46,48),firstArc,secondArc)<=2.25;
}
function sample(x,y,theme){
  const {tile,ink,accent}=themes[theme];
  const qx=Math.abs(x-32)-16,qy=Math.abs(y-32)-16;
  if(Math.hypot(Math.max(qx,0),Math.max(qy,0))+Math.min(Math.max(qx,qy),0)>14)return null;
  if(Math.hypot(x-46,y-48)<=5.5)return rgba(accent);
  if(Math.hypot(x-18,y-16)<=4.5||Math.hypot(x-32,y-32)<=4.5||onRoute(x,y))return rgba(ink);
  return rgba(tile);
}
function crc32(data){
  let value=0xffffffff;
  for(const byte of data){value^=byte;for(let bit=0;bit<8;bit++)value=(value>>>1)^((value&1)?0xedb88320:0);}
  return (value^0xffffffff)>>>0;
}
function chunk(type,data){
  const content=Buffer.concat([Buffer.from(type),data]);
  const length=Buffer.alloc(4),crc=Buffer.alloc(4);
  length.writeUInt32BE(data.length);crc.writeUInt32BE(crc32(content));
  return Buffer.concat([length,content,crc]);
}
function png(size,theme){
  const samples=4,total=samples*samples,rows=Buffer.alloc((size*4+1)*size);
  for(let py=0;py<size;py++)for(let px=0;px<size;px++){
    const sum=[0,0,0];let covered=0;
    for(let sy=0;sy<samples;sy++)for(let sx=0;sx<samples;sx++){
      const color=sample((px+(sx+.5)/samples)*64/size,(py+(sy+.5)/samples)*64/size,theme);
      if(color){covered++;for(let c=0;c<3;c++)sum[c]+=color[c];}
    }
    const offset=py*(size*4+1)+1+px*4;
    for(let c=0;c<3;c++)rows[offset+c]=covered?Math.round(sum[c]/covered):0;
    rows[offset+3]=Math.round(covered/total*255);
  }
  const header=Buffer.alloc(13);header.writeUInt32BE(size,0);header.writeUInt32BE(size,4);header[8]=8;header[9]=6;
  return Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]),chunk('IHDR',header),chunk('IDAT',deflateSync(rows)),chunk('IEND',Buffer.alloc(0))]);
}
await mkdir(output,{recursive:true});
await writeFile(path.join(output,'icon.svg'),svg('light'));
await writeFile(path.join(output,'logo-dark.svg'),svg('dark'));
await writeFile(path.join(output,'icon.png'),png(64,'light'));
await writeFile(path.join(output,'logo.png'),png(256,'light'));
await writeFile(path.join(output,'logo-dark.png'),png(256,'dark'));
console.log('Built Codex Trace SVG and PNG brand assets');
