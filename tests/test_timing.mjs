import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { build, transform } from 'esbuild';
import { trajectoryTiming } from '../src/trajectory-order.js';

const formatters = await build({
  entryPoints: [
    fileURLToPath(
      new URL(
        '../vendor/dsh/packages/client/ui-trajectory/src/client/trajectory-record.ts',
        import.meta.url,
      ),
    ),
  ],
  bundle: true,
  write: false,
  format: 'esm',
});
const { formatElapsedSeconds } = await import(
  `data:text/javascript;base64,${Buffer.from(formatters.outputFiles[0].text).toString('base64')}`
);
const table = await readFile(
  new URL(
    '../vendor/dsh/packages/client/ui-trajectory/src/client/TrajectoryTable.tsx',
    import.meta.url,
  ),
  'utf8',
);
const stateSource = table.match(/function stateOf\([\s\S]*?\n}\n/)[0];
const compiled = await transform(stateSource, { loader: 'tsx' });
const context = {};
vm.runInNewContext(compiled.code + '\nglobalThis.state = stateOf;', context);

test('completed clock-anomalous compaction stays complete and its elapsed time is unavailable', () => {
  const recorded = { kind: 'compacted', startedAt: 2000, timeSeconds: null, timingAnomaly: true };
  const cell = trajectoryTiming(recorded);
  assert.equal(context.state({ cell }), 'complete');
  assert.equal(
    formatElapsedSeconds(cell.timeSeconds, (key) => key),
    '—',
  );
  assert.equal(recorded.timeSeconds, null);
  assert.equal(cell.startedAt, 2000);
});

test('request fallback timing displays unknown instead of a fabricated zero', () => {
  const recorded = { startedAt: 2000, completedAt: 1500, timingAnomaly: true };
  const request = trajectoryTiming(recorded);
  const seconds = Math.max(0, (request.completedAt - request.startedAt) / 1000);
  assert.equal(
    formatElapsedSeconds(seconds, (key) => key),
    '—',
  );
  assert.equal(recorded.completedAt, 1500);
});

test('normal zero duration and running compaction retain their original behavior', () => {
  const running = { kind: 'compacted', timeSeconds: null };
  assert.equal(trajectoryTiming(running), running);
  assert.equal(context.state({ cell: trajectoryTiming(running) }), 'running');
  const complete = { timeSeconds: 0, completedAt: 2000 };
  assert.equal(trajectoryTiming(complete), complete);
  assert.notEqual(
    formatElapsedSeconds(complete.timeSeconds, (_key, params) => `${params.ms}ms`),
    '—',
  );
});
