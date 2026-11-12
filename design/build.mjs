import {build} from 'esbuild';
import {readFile,writeFile} from 'node:fs/promises';
const result=await build({entryPoints:['design/app.jsx'],bundle:true,write:false,minify:true,format:'iife',jsx:'automatic',define:{'process.env.NODE_ENV':'"production"'}});
const css=await readFile('design/styles.css','utf8');
const script=result.outputFiles[0].text.replaceAll('</script','<\\/script');
const html=`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light dark"><title>轨迹 · Rollout Viewer 设计评审</title><style>${css}</style></head><body><div id="root"></div><script>${script}</script></body></html>`;
await writeFile('design/rollout-viewer.html',html);
console.log(`Built self-contained prototype: ${(Buffer.byteLength(html)/1024).toFixed(1)} KiB`);
