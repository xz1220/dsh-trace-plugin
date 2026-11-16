import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const read=relative=>readFile(new URL('../'+relative,import.meta.url),'utf8');

test('Antigravity delivery stays aligned with upstream branding and version',async()=>{
  const [packageText,nativeManifestText,codexManifestText,native,core,backend,client]=await Promise.all([
    read('package.json'),read('plugins/antigravity-dsh-trace/plugin.json'),
    read('plugins/codex-dsh-trace/.codex-plugin/plugin.json'),
    read('plugins/antigravity-dsh-trace/assets/viewer.html'),
    read('plugins/codex-dsh-trace/assets/viewer.html'),
    read('plugins/antigravity-dsh-trace/server/main.py'),
    read('plugins/antigravity-dsh-trace/sidecars/trace-viewer/rpc-client.mjs'),
  ]);
  const {version}=JSON.parse(packageText);
  assert.equal(JSON.parse(nativeManifestText).version,version);
  assert.equal(backend.match(/^VERSION = '([^']+)'/m)?.[1],version);
  assert.equal(client.match(/clientInfo: \{name: 'antigravity-dsh-trace', version: '([^']+)'/)?.[1],version);
  assert.equal(core.match(/<title>([^<]+)<\/title>/)?.[1],JSON.parse(codexManifestText).interface.displayName);
  assert.equal(native.match(/<title>([^<]+)<\/title>/)?.[1],'Antigravity DSH Trace');
  assert.ok(native.includes(`name="rollout-viewer-version" content="${version}"`));
  const bootstrap='window.__ROLLOUT_HOST__={"name":"Antigravity DSH Trace","source":"antigravity"}';
  assert.ok(native.includes('<script>'+bootstrap+';</script><script>'),'Native host identity must precede the shared UI.');
  assert.ok(!core.includes(bootstrap),'The default Codex artifact must retain its own host identity.');
  assert.ok(!native.includes('<!--BOOTSTRAP-->'));
});
