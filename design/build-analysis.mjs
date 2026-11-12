import {build} from 'esbuild';
import {readFile,writeFile} from 'node:fs/promises';
import {ensureSources} from './fetch-dsh-sources.mjs';
await ensureSources();
const ranges={
 'toolbar':['TrajectoryToolbar.module.css',1,52],
 'row':['TrajectoryTable.module.css',117,195],
 'tags':['TrajectoryTable.module.css',477,520],
 'semantic':['TrajectoryTable.module.css',613,739],
 'inspector':['TrajectoryTable.module.css',888,1047],
 'narrow':['TrajectoryTable.module.css',523,569],
 'drawer':['TrajectoryTable.module.css',2069,2081],
 'performance':['TrajectoryTable.tsx',48,53],
 'tabs':['TrajectoryTable.tsx',992,1027],
 'timing':['TrajectoryTimeline.module.css',130,221],
 'typography':['gradient-shadow-text.css',234,255]
};
const excerpts={};
for(const[key,[file,start,end]] of Object.entries(ranges)){const lines=(await readFile(`design/dsh-source/${file}`,'utf8')).split('\n');excerpts[key]={file,start,end,code:lines.slice(start-1,end).join('\n')};}
await writeFile('design/analysis-excerpts.json',JSON.stringify(excerpts));
const r=await build({entryPoints:['design/dsh-analysis.jsx'],bundle:true,write:false,minify:true,format:'iife',jsx:'automatic',outfile:'design/analysis-bundle.js',define:{'process.env.NODE_ENV':'"production"'}});
const js=r.outputFiles.find(f=>f.path.endsWith('.js')).text.replaceAll('</script','<\\/script');
const css=r.outputFiles.find(f=>f.path.endsWith('.css')).text;
const license=await readFile('design/DSH-LICENSE.txt','utf8');
await writeFile('design/dsh-design-system.html',`<!doctype html>\n<!-- Original DSH theme and component styles:\n${license}\nSource commit e8f7b93a344964de3dca1ace9e72b6e4d6de87cb. -->\n<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DSH 轨迹 · 设计系统拆解</title><style>${css}</style></head><body><div id="root"></div><script>${js}</script></body></html>`);
console.log('Built source-backed DSH design-system analysis');
