import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';
const result = await build({
  entryPoints: [fileURLToPath(new URL('../src/preferences.js', import.meta.url))],
  bundle: true,
  write: false,
  format: 'esm',
});
const { createBooleanPreference } = await import(
  `data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`
);

test('fresh views default to equal widths and preferences survive recreation', () => {
  const data = new Map(),
    storage = () => ({
      getItem: (key) => data.get(key),
      setItem: (key, value) => data.set(key, value),
    });
  const first = createBooleanPreference('duration', { storage });
  assert.equal(first.getSnapshot(), false);
  first.set(true);
  assert.equal(createBooleanPreference('duration', { storage }).getSnapshot(), true);
});
test('shared subscribers keep a preference when storage is unavailable', () => {
  const preference = createBooleanPreference('wrap', {
    storage: () => {
      throw new Error('opaque origin');
    },
  });
  const observed = [];
  const stop = preference.subscribe(() => observed.push(preference.getSnapshot()));
  preference.set(true);
  preference.set(true);
  stop();
  preference.set(false);
  assert.deepEqual(observed, [true]);
  assert.equal(preference.getSnapshot(), false);
});
test('invalid saved values cannot become truthy UI preferences', () => {
  for (const raw of ['"false"', '{}', '1', 'invalid']) {
    assert.equal(
      createBooleanPreference('duration', {
        storage: () => ({ getItem: () => raw }),
      }).getSnapshot(),
      false,
    );
  }
});
