import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { apiError } from '../src/errors.js';

async function invoke(response) {
  const html = await readFile(
    new URL('../plugins/codex-dsh-trace/server/bridge-harness.html', import.meta.url),
    'utf8',
  );
  const source = html
    .match(/<script>([\s\S]*?)<\/script>/)[1]
    .replace('__CONFIG__', JSON.stringify({ threadId: 'synthetic-thread', coldStart: true }));
  const replies = [];
  let receive;
  const frame = { contentWindow: { postMessage: (value) => replies.push(value) } };
  vm.runInNewContext(source, {
    window: {},
    document: { querySelector: () => frame },
    location: { origin: 'http://127.0.0.1:43123' },
    addEventListener: (_name, handler) => {
      receive = handler;
    },
    fetch: async () => response,
  });
  await receive({
    source: frame.contentWindow,
    data: { jsonrpc: '2.0', id: 'request', method: 'tools/call', params: { name: 'probe' } },
  });
  return replies[0].result;
}

test('harness preserves coded HTTP failures and localization parameters', async () => {
  const failure = {
    error: '录制格式不支持。',
    errorCode: 'unsupported_schema',
    errorParams: { version: 99 },
  };
  const result = await invoke({ ok: false, json: async () => failure });
  assert.equal(result.isError, true);
  const error = apiError(result.structuredContent);
  assert.equal(error.code, 'unsupported_schema');
  assert.deepEqual(error.params, { version: 99 });
  assert.equal(error.message, failure.error);
});

test('harness passes normal tool error envelopes through unchanged', async () => {
  const envelope = { isError: true, structuredContent: { errorCode: 'content_updated' } };
  const result = await invoke({ ok: true, json: async () => envelope });
  assert.equal(result, envelope);
});

test('harness keeps legacy text errors and a safe fallback for unknown HTTP bodies', async () => {
  for (const body of [{ error: 'Legacy failure' }, null]) {
    const result = await invoke({ ok: false, json: async () => body });
    const error = apiError(result.structuredContent);
    assert.equal(error.code, 'trace_error');
    assert.equal(error.message, body?.error || 'Local preview request failed');
  }
});
