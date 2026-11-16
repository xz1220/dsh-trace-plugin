import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';
import { File as BufferFile } from 'node:buffer';
import { webcrypto } from 'node:crypto';

const root = fileURLToPath(new URL('../vendor/dsh/', import.meta.url));
const result = await build({
  entryPoints: [`${root}packages/client/ui-file-drag/src/client/transfers.ts`],
  bundle: true,
  write: false,
  format: 'esm',
  platform: 'browser',
  target: 'es2022',
  alias: {
    '@deepseek-ai/dsh-util-file-drag': `${root}packages/util/file-drag/src/index.ts`,
    '@deepseek-ai/dsh-util-crypto': `${root}packages/util/crypto/src/index.ts`,
  },
});
const { FileTransfers } = await import(
  `data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`
);
const previousWindow = globalThis.window;
globalThis.window = new EventTarget();
globalThis.File ??= BufferFile;
if (!globalThis.crypto)
  Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true });
after(() => {
  if (previousWindow === undefined) delete globalThis.window;
  else globalThis.window = previousWindow;
});

function transfer() {
  const values = new Map();
  return {
    items: {
      clear() {
        values.clear();
      },
    },
    setData(key, value) {
      values.set(key, value);
    },
    getData(key) {
      return values.get(key) || '';
    },
  };
}

test('original browser drag retains exact bytes until drag end', async () => {
  const owner = new FileTransfers(undefined, () => assert.fail('unexpected drag failure'));
  const signal = new AbortController().signal;
  const bytes = new Uint8Array([0, 1, 42, 255]);
  const prepared = await owner.prepare(
    {
      kind: 'blob',
      blob: new Blob([bytes], { type: 'image/png' }),
      name: 'image',
      mediaType: 'image/png',
    },
    signal,
  );
  const data = transfer(),
    element = new EventTarget();
  assert.equal(prepared.start(data, element), true);
  assert.equal(data.effectAllowed, 'copy');
  const download = data.getData('DownloadURL');
  assert.match(download, /^image\/png:image\.png:blob:/);
  const url = download.slice('image/png:image.png:'.length);
  assert.deepEqual(new Uint8Array(await owner.read(data).arrayBuffer()), bytes);
  assert.equal(owner.read(transfer()), undefined);
  prepared.release();
  assert.deepEqual(new Uint8Array(await (await fetch(url)).arrayBuffer()), bytes);
  element.dispatchEvent(new Event('dragend'));
  assert.equal(owner.read(data), undefined);
  await assert.rejects(fetch(url));
  owner.dispose();
});

test('recorded export names use the original safe MIME-based naming', async () => {
  const owner = new FileTransfers(undefined, () => {});
  const prepared = await owner.prepare(
    {
      kind: 'blob',
      blob: new Blob(['image'], { type: 'image/jpeg' }),
      name: 'CON.png',
      mediaType: 'image/jpeg',
    },
    new AbortController().signal,
  );
  const data = transfer();
  prepared.start(data, new EventTarget());
  assert.equal(owner.read(data).name, '_CON.jpg');
  assert.equal(owner.read(data).type, 'image/jpeg');
  prepared.release();
  owner.dispose();
});

test('cancelled image preparation creates no usable transfer', async () => {
  const owner = new FileTransfers(undefined, () => {}),
    controller = new AbortController();
  controller.abort();
  await assert.rejects(
    owner.prepare(
      { kind: 'blob', blob: new Blob(['image']), mediaType: 'image/png' },
      controller.signal,
    ),
    { name: 'AbortError' },
  );
  owner.dispose();
});
