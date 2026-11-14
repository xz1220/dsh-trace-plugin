import {build} from 'esbuild';
import {readFile,writeFile} from 'node:fs/promises';
import path from 'node:path';
import './verify-dsh.mjs';
import './sync-trajectory-locales.mjs';
const root=path.resolve('vendor/dsh');
const result=await build({entryPoints:['src/viewer.jsx'],bundle:true,write:false,minify:true,format:'iife',jsx:'automatic',outfile:'plugins/rollout-viewer/assets/viewer.js',
 alias:{'@deepseek-ai/dsh-client-ui-primitives':path.join(root,'primitives.ts'),
 '@deepseek-ai/dsh-util-values':path.join(root,'packages/util/values/src/index.ts'),
 '@deepseek-ai/dsh-util-code-language':path.join(root,'packages/util/code-language/src/index.ts'),
 '@deepseek-ai/dsh-util-workspace-path':path.join(root,'packages/util/workspace-path/src/index.ts'),
 '@deepseek-ai/dsh-util-file-drag':path.join(root,'packages/util/file-drag/src/index.ts'),
 '@deepseek-ai/dsh-util-crypto':path.join(root,'packages/util/crypto/src/index.ts')},
 loader:{'.woff2':'dataurl','.woff':'dataurl','.ttf':'dataurl'},
 define:{'process.env.NODE_ENV':'"production"'}});
const js=result.outputFiles.find(f=>f.path.endsWith('.js')).text.replaceAll('</script','<\\/script');
const css=result.outputFiles.find(f=>f.path.endsWith('.css')).text;
const license=await readFile('design/DSH-LICENSE.txt','utf8');
await writeFile('plugins/rollout-viewer/assets/viewer.html',`<!doctype html>\n<!-- DSH component styles: ${license} -->\n<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Rollout Viewer</title><style>${css}</style></head><body><div id="root"></div><!--BOOTSTRAP--><script>${js}</script></body></html>`);
console.log('Built Rollout Viewer MCP App');
