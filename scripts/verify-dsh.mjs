import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
const root=new URL('../vendor/dsh/',import.meta.url);
const source=JSON.parse(await readFile(new URL('upstream.json',root),'utf8'));
const patches=JSON.parse(await readFile(new URL('patches.json',root),'utf8'));
const allowed=new Map(patches.files.map(file=>[file.path,file.sha256]));
let unchanged=0,patched=0;
for(const file of source.files){
  const actual=createHash('sha256').update(await readFile(new URL(file.path,root))).digest('hex');
  if(actual===file.sha256){unchanged++;continue;}
  if(allowed.get(file.path)!==actual)throw new Error(`Unreviewed DSH source change: ${file.path}`);
  patched++;
}
console.log(`DSH ${source.commit.slice(0,8)}: ${unchanged} unchanged files, ${patched} documented adapters.`);
