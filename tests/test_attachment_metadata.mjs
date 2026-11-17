import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { transform } from 'esbuild';

const table = await readFile(
  new URL(
    '../vendor/dsh/packages/client/ui-trajectory/src/client/TrajectoryTable.tsx',
    import.meta.url,
  ),
  'utf8',
);
const formatter = await readFile(
  new URL('../vendor/dsh/packages/client/ui-primitives/src/file-size.ts', import.meta.url),
  'utf8',
);
const source = table.match(/function recordAttachments\([\s\S]*?\n}\n/)[0];
const compiled = await transform(formatter.replace('export function', 'function') + '\n' + source, {
  loader: 'ts',
});
const context = { fileExtension: () => '' };
vm.runInNewContext(compiled.code + '\nglobalThis.attachments = recordAttachments;', context);
const metadata = (bytes) =>
  context.attachments(
    [{ type: 'image', attachment: { mediaType: 'image/svg+xml', bytes } }],
    () => 'recorded image',
  )[0].metadata;

test('attachment metadata formats exact bytes and omits unknown or invalid sizes', () => {
  assert.equal(metadata(16), 'image/svg+xml · 16B');
  assert.equal(metadata(0), 'image/svg+xml · 0B');
  for (const unknown of [undefined, null, Number.NaN, Infinity, -1, 1.5, '16']) {
    assert.equal(metadata(unknown), 'image/svg+xml');
  }
});
