import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';

const result=await build({entryPoints:[fileURLToPath(new URL('../src/locale.js',import.meta.url))],bundle:true,write:false,format:'esm',platform:'browser'});
const {t,dictionary,dictionaries,supportedLocales,translatorFor}=await import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);

test('all literal translation calls in the shipped DSH controls resolve',async()=>{
  for(const file of ['TrajectoryTable.tsx','TrajectoryTimeline.tsx','TrajectoryToolbar.tsx','timeline.ts','trajectory-record.ts']){
    const source=await readFile(new URL(`../vendor/dsh/packages/client/ui-trajectory/src/client/${file}`,import.meta.url),'utf8');
    const keys=[...source.matchAll(/\bt\(\s*['"]([^'"]+)['"]/g)].map(match=>match[1]);
    for(const key of keys)assert.ok(Object.hasOwn(dictionary,key),`${file}: untranslated ${key}`);
  }
});
test('common copy and expansion labels use the upstream Chinese vocabulary',()=>{
  assert.equal(t('copy.json'),'复制 JSON');assert.equal(t('expand'),'展开');assert.equal(t('collapse'),'收起');
  assert.equal(t('copy.optionsHint',{action:'复制值'}),'复制值；右键点击可选择复制方式');
});
test('all eight host locales resolve core controls and request evidence tabs',()=>{
  assert.equal(supportedLocales.length,8);
  for(const locale of supportedLocales){
    const translate=translatorFor(locale+'-XX');
    for(const key of Object.keys(dictionary))assert.ok(Object.hasOwn(dictionaries[locale],key),`${locale}: missing ${key}`);
    assert.notEqual(translate('toolbar.duration'),'toolbar.duration');
    assert.notEqual(translate('codex.prompt'),'codex.prompt');
  }
  assert.equal(translatorFor('en-US')('toolbar.search'),'Search trajectory');
  assert.equal(translatorFor('unsupported').locale,'en');
});
test('backend search group templates match the displayed pinned dictionaries',async()=>{
  const labels=JSON.parse(await readFile(new URL('../plugins/codex-dsh-trace/server/trajectory-locales.json',import.meta.url),'utf8'));
  for(const locale of supportedLocales)assert.deepEqual(labels[locale],{step:dictionaries[locale]['group.step'],compaction:dictionaries[locale]['group.compaction']});
});
