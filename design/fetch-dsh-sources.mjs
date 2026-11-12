import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
const execute=promisify(execFile);
const root=new URL('./',import.meta.url);
export async function ensureSources(){
 const manifest=JSON.parse(await readFile(new URL('dsh-sources.json',root),'utf8'));
 await mkdir(new URL('dsh-source/',root),{recursive:true});
 const sha=bytes=>createHash('sha1').update(`blob ${bytes.length}\0`).update(bytes).digest('hex');
 await Promise.all(manifest.files.map(async file=>{
  const target=new URL('dsh-source/'+file.file,root);
  try{
   const existing=await readFile(target);if(sha(existing)===file.sha)return;
   const normalized=Buffer.from(existing.toString('utf8').replace(/\n+$/,'\n'));
   if(sha(normalized)===file.sha){await writeFile(target,normalized);return;}
  }catch(error){if(error.code!=='ENOENT')throw error;}
  const {stdout}=await execute('curl',['--fail','--silent','--show-error','--location','--connect-timeout','10','--max-time','30',`https://raw.githubusercontent.com/${manifest.repository}/${manifest.commit}/${file.path}`],{encoding:'buffer',maxBuffer:10*1024*1024});
  const bytes=Buffer.from(stdout);
  if(sha(bytes)!==file.sha)throw new Error(`${file.file}: source hash mismatch`);
  await writeFile(target,bytes);
 }));
}
if(process.argv[1]===fileURLToPath(import.meta.url)){await ensureSources();console.log('Pinned DSH sources verified');}
