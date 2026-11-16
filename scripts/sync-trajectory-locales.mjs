// Keep server-side metadata search terms identical to the displayed upstream labels.
import {build} from 'esbuild';
import {readFile,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const result=await build({entryPoints:[fileURLToPath(new URL('../src/locale.js',import.meta.url))],bundle:true,write:false,format:'esm'});
const {dictionaries}=await import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);
const data=Object.fromEntries(Object.entries(dictionaries).map(([locale,dictionary])=>[locale,{step:dictionary['group.step'],compaction:dictionary['group.compaction']}]));
const target=new URL('../plugins/codex-dsh-trace/server/trajectory-locales.json',import.meta.url),text=JSON.stringify(data,null,2)+'\n';
if(await readFile(target,'utf8').catch(()=>null)!==text)await writeFile(target,text);
