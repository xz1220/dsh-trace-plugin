import './build-plugin.mjs';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import path from 'node:path';

const root=path.resolve(import.meta.dirname,'..');
const output=path.join(root,'plugins/antigravity-dsh-trace/assets');
await mkdir(output,{recursive:true});
const original=await readFile(path.join(root,'plugins/codex-dsh-trace/assets/viewer.html'),'utf8');
const profile=JSON.stringify({name:'Antigravity DSH Trace',source:'antigravity'}).replaceAll('<','\\u003c');
if(!/<title>[^<]*<\/title>/.test(original)||!original.includes('<!--BOOTSTRAP-->'))throw new Error('Shared viewer template is missing its title or bootstrap marker.');
const html=original.replace(/<title>[^<]*<\/title>/,'<title>Antigravity DSH Trace</title>')
  .replace('<!--BOOTSTRAP-->',`<script>window.__ROLLOUT_HOST__=${profile};</script>`);
await writeFile(path.join(output,'viewer.html'),html);
console.log('Built Antigravity DSH Trace sidecar UI');
