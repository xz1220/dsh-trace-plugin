import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { createHash } from 'node:crypto';
import { apiError } from '../src/errors.js';

async function loader() {
  const source = await readFile(new URL('../src/images.jsx', import.meta.url), 'utf8');
  // Exercise the actual non-rendering loader, with only the browser decoder replaced.
  const start = source.indexOf('const cache = new Map();');
  const end = source.indexOf('const reportDragFailure');
  assert.ok(start >= 0 && end > start);
  let decodes = 0;
  const context = {
    apiError,
    Image: class {
      async decode() {
        decodes += 1;
      }
    },
  };
  vm.runInNewContext(
    source.slice(start, end).replace('export const loadImage', 'const loadImage') +
      '\nglobalThis.load = loadImage;',
    context,
  );
  return { load: context.load, decodes: () => decodes };
}

const svg = (color) =>
  'data:image/svg+xml,' +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"><rect width="1" height="1" fill="${color}"/></svg>`,
  );
const attachment = (url) => ({
  recordedUrl: url,
  attachmentId: createHash('sha256').update(url).digest('hex'),
});

test('distinct inline image identities show their own URL and reuse only matching content', async () => {
  const { load, decodes } = await loader();
  const red = attachment(svg('red'));
  const blue = attachment(svg('blue'));
  assert.equal(await load(red), red.recordedUrl);
  assert.equal(await load(blue), blue.recordedUrl);
  assert.equal(await load({ ...red }), red.recordedUrl);
  assert.equal(load.peek(blue), blue.recordedUrl);
  assert.equal(decodes(), 2);
});

test('recorded image loader refuses arbitrary remote URLs', async () => {
  const { load, decodes } = await loader();
  await assert.rejects(
    load(attachment('https://example.invalid/private')),
    (error) => error.code === 'image_unavailable',
  );
  assert.equal(decodes(), 0);
});
