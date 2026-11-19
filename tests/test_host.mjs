import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHost } from '../src/host.js';

function setup(t, { output, open, initialization, preview } = {}) {
  const previous = globalThis.window,
    handlers = new Map(),
    calls = [],
    results = [],
    errors = [],
    errorObjects = [],
    contexts = [];
  const send = (value) =>
    handlers.get('message')?.({ source: parent, data: { jsonrpc: '2.0', ...value } });
  const parent = {
    postMessage(message) {
      calls.push(message);
      if (message.id === undefined) return;
      Promise.resolve().then(async () => {
        const result =
          message.method === 'ui/initialize'
            ? initialization || { protocolVersion: '2026-01-26', hostContext: { theme: 'light' } }
            : await open?.(message.params);
        send({ id: message.id, result });
      });
    },
  };
  globalThis.window = {
    parent,
    openai: { toolOutput: output },
    __ROLLOUT_PREVIEW__: preview,
    addEventListener: (type, handler) => handlers.set(type, handler),
    removeEventListener: (type, handler) => {
      if (handlers.get(type) === handler) handlers.delete(type);
    },
  };
  const host = createHost({
    onResult: (value) => results.push(value.structuredContent || value),
    onContext: (value) => contexts.push(value),
    onError: (error) => {
      errors.push(error.message);
      errorObjects.push(error);
    },
  });
  t.after(() => {
    host.dispose();
    globalThis.window = previous;
  });
  return { host, calls, results, errors, errorObjects, contexts, handlers, send };
}

test('cold sidebar reads its existing history without a model notification', async (t) => {
  const history = {
    view: 'trace',
    currentThreadId: 'root',
    trace: { id: 'old' },
    rows: [{ id: 'request:old' }],
  };
  const state = setup(t, {
    open: (params) => {
      assert.equal(params.name, 'open_rollout_viewer');
      return { structuredContent: history };
    },
  });
  await state.host.start();
  assert.deepEqual(state.results, [history]);
  assert.deepEqual(
    state.calls.map((call) => call.method),
    ['ui/initialize', 'ui/notifications/initialized', 'tools/call'],
  );
  assert.deepEqual(state.errors, []);
});

test('unrelated initial tool output does not suppress the history read', async (t) => {
  const history = { view: 'trace', trace: { id: 'history' }, rows: [] };
  const state = setup(t, { output: { traces: [] }, open: () => ({ structuredContent: history }) });
  await state.host.start();
  assert.deepEqual(state.results, [history]);
  assert.equal(state.calls.filter((call) => call.method === 'tools/call').length, 1);
});

test('a supplied native launch does not issue a second startup read', async (t) => {
  const launch = { view: 'open', trace: { id: 'supplied' } };
  const state = setup(t, { output: launch });
  await state.host.start();
  assert.deepEqual(state.results, [launch]);
  assert.equal(
    state.calls.some((call) => call.method === 'tools/call'),
    false,
  );
});

test('a delayed startup read cannot replace a newer explicit launch', async (t) => {
  let complete, started;
  const waiting = new Promise((resolve) => {
    started = resolve;
  });
  const state = setup(t, {
    open: () => {
      started();
      return new Promise((resolve) => {
        complete = resolve;
      });
    },
  });
  const ready = state.host.start();
  await waiting;
  const newer = { view: 'open', trace: { id: 'explicit' } };
  state.send({ method: 'ui/notifications/tool-result', params: { structuredContent: newer } });
  complete({ structuredContent: { view: 'select', traces: [] } });
  await ready;
  assert.deepEqual(state.results, [newer]);
});

test('startup tool errors are reported rather than leaving an empty loading view', async (t) => {
  const state = setup(t, {
    open: () => ({ isError: true, structuredContent: { error: 'Capture unavailable' } }),
  });
  await assert.rejects(state.host.start(), /Capture unavailable/);
  assert.deepEqual(state.errors, ['Capture unavailable']);
  assert.deepEqual(state.results, []);
});

test('startup errors retain structured localization codes and parameters', async (t) => {
  const data = {
    error: 'Old server fallback',
    errorCode: 'unsupported_schema',
    errorParams: { version: 99 },
  };
  const state = setup(t, { open: () => ({ isError: true, structuredContent: data }) });
  await assert.rejects(state.host.start(), (error) => {
    assert.equal(error.message, data.error);
    assert.equal(error.code, data.errorCode);
    assert.deepEqual(error.params, data.errorParams);
    return true;
  });
  assert.equal(state.errorObjects[0].code, 'unsupported_schema');
});

test('native tool calls preserve coded errors and support legacy text-only envelopes', async (t) => {
  const state = setup(t, {
    output: { view: 'select', traces: [] },
    open: (params) =>
      params.name === 'legacy'
        ? { isError: true, content: [{ type: 'text', text: 'Legacy tool failure' }] }
        : {
            structuredContent: {
              error: 'Native fallback',
              errorCode: 'invalid_tool_arguments',
              errorParams: { field: 'limit' },
            },
          },
  });
  await state.host.start();
  await assert.rejects(state.host.call('coded'), (error) => {
    assert.equal(error.code, 'invalid_tool_arguments');
    assert.deepEqual(error.params, { field: 'limit' });
    return true;
  });
  await assert.rejects(state.host.call('legacy'), /Legacy tool failure/);
});

test('preview calls preserve HTTP errors and send same-origin credentials', async (t) => {
  const previousFetch = globalThis.fetch;
  const state = setup(t, { preview: { traceId: 'fixture' } });
  t.after(() => {
    globalThis.fetch = previousFetch;
  });
  globalThis.fetch = async (url, options) => {
    assert.equal(url, '/api');
    assert.equal(options.credentials, 'same-origin');
    assert.deepEqual(JSON.parse(options.body), {
      name: 'get_rollout_overview',
      arguments: { traceId: 'fixture' },
    });
    return {
      ok: false,
      json: async () => ({
        error: 'HTTP fallback',
        errorCode: 'forbidden',
        errorParams: { port: 1234 },
      }),
    };
  };
  await state.host.start();
  assert.equal(state.calls.length, 0);
  await assert.rejects(state.host.call('get_rollout_overview', { traceId: 'fixture' }), (error) => {
    assert.equal(error.message, 'HTTP fallback');
    assert.equal(error.code, 'forbidden');
    assert.deepEqual(error.params, { port: 1234 });
    return true;
  });
});

test('preview successful calls unwrap structured results and reject tool error envelopes', async (t) => {
  const previousFetch = globalThis.fetch;
  const state = setup(t, { preview: true });
  t.after(() => {
    globalThis.fetch = previousFetch;
  });
  const data = { rows: [{ id: 'fixture-row' }] };
  globalThis.fetch = async () => ({ ok: true, json: async () => ({ structuredContent: data }) });
  assert.deepEqual(await state.host.call('get_rollout_overview'), data);
  globalThis.fetch = async () => ({
    ok: true,
    json: async () => ({
      isError: true,
      structuredContent: { error: 'Tool fallback', errorCode: 'record_not_found' },
    }),
  });
  await assert.rejects(
    state.host.call('get_rollout_detail'),
    (error) => error.code === 'record_not_found',
  );
  globalThis.fetch = async () => ({ ok: true, json: async () => ({ plain: 'legacy result' }) });
  assert.deepEqual(await state.host.call('legacy'), { plain: 'legacy result' });
});

test('host context and global output updates are delivered while foreign messages are ignored', async (t) => {
  const state = setup(t, { output: { view: 'select', traces: [] } });
  await state.host.start();
  state.handlers.get('message')({
    source: {},
    data: {
      jsonrpc: '2.0',
      method: 'ui/notifications/host-context-changed',
      params: { locale: 'wrong' },
    },
  });
  state.handlers.get('message')({
    source: window.parent,
    data: { jsonrpc: '1.0', method: 'ui/notifications/host-context-changed' },
  });
  state.send({ method: 'ui/notifications/host-context-changed', params: { locale: 'en-US' } });
  state.send({ method: 'ui/notifications/host-context-changed' });
  state.handlers.get('openai:set_globals')({
    detail: { globals: { locale: 'zh-CN', toolOutput: { view: 'open', trace: { id: 'global' } } } },
  });
  state.handlers.get('openai:set_globals')({});
  assert.deepEqual(state.contexts, [
    { theme: 'light' },
    { locale: 'en-US' },
    {},
    { locale: 'zh-CN', toolOutput: { view: 'open', trace: { id: 'global' } } },
    {},
  ]);
  assert.equal(state.results.at(-1).trace.id, 'global');
});

test('teardown rejects pending work with a coded closed-panel error', async (t) => {
  let waiting;
  const started = new Promise((resolve) => {
    waiting = resolve;
  });
  const state = setup(t, {
    output: { view: 'select', traces: [] },
    open: () => {
      waiting();
      return new Promise(() => {});
    },
  });
  await state.host.start();
  const request = state.host.call('get_rollout_detail');
  await started;
  state.send({ id: 'teardown', method: 'ui/resource-teardown' });
  await assert.rejects(request, (error) => error.code === 'panel_closed');
  assert.deepEqual(state.calls.at(-1), { jsonrpc: '2.0', id: 'teardown', result: {} });
  await assert.rejects(
    state.host.call('get_rollout_detail'),
    (error) => error.code === 'panel_closed',
  );
  assert.equal(state.handlers.size, 0);
});

test('unsupported host versions reject startup with a localizable error', async (t) => {
  const state = setup(t, { initialization: { protocolVersion: 'future' } });
  await assert.rejects(state.host.start(), (error) => error.code === 'unsupported_host');
  assert.equal(state.errorObjects[0].code, 'unsupported_host');
});

test('empty JSON-RPC error messages fall back to the localizable tool_failed code', async (t) => {
  const state = setup(t, { output: { view: 'select', traces: [] } });
  await state.host.start();
  const pendingEmpty = state.host.call('get_rollout_detail');
  const emptyId = state.calls.at(-1).id;
  state.send({ id: emptyId, error: { code: -32603, message: '' } });
  await assert.rejects(pendingEmpty, (error) => error.code === 'tool_failed');
  const pendingExplicit = state.host.call('get_rollout_detail');
  const explicitId = state.calls.at(-1).id;
  state.send({ id: explicitId, error: { code: -32603, message: 'Host refused tool' } });
  await assert.rejects(pendingExplicit, /Host refused tool/);
});
