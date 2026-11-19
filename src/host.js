/* MCP Apps bridge. The loopback transport is only for authenticated local preview. */
import { apiError } from './errors.js';
import { VERSION } from './version.js';
export function createHost({ onResult, onContext, onError }) {
  const preview = window.__ROLLOUT_PREVIEW__;
  const pending = new Map();
  let counter = 0,
    ready = false,
    connecting,
    closed = false,
    receivedLaunch = false;
  function deliver(result) {
    const value = result?.structuredContent || result;
    if (
      !value ||
      !['open', 'select', 'trace'].includes(value.view) ||
      (value.view === 'trace' && !Array.isArray(value.rows))
    )
      return;
    receivedLaunch = true;
    onResult(result);
  }
  const post = (data) => window.parent.postMessage({ jsonrpc: '2.0', ...data }, '*');
  const request = (method, params) =>
    new Promise((resolve, reject) => {
      const id = `rollout-viewer-${++counter}`;
      const timer = setTimeout(() => {
        pending.delete(id);
        reject(apiError({ errorCode: 'connection_timeout' }));
      }, 20000);
      pending.set(id, { resolve, reject, timer });
      post({ id, method, params });
    });
  function receive(event) {
    if (event.source !== window.parent || event.data?.jsonrpc !== '2.0') return;
    const message = event.data;
    if (message.id !== undefined && !message.method && pending.has(message.id)) {
      const p = pending.get(message.id);
      pending.delete(message.id);
      clearTimeout(p.timer);
      message.error
        ? p.reject(
            message.error.message
              ? new Error(message.error.message)
              : apiError({ errorCode: 'tool_failed' }),
          )
        : p.resolve(message.result);
      return;
    }
    if (message.method === 'ui/notifications/tool-result') deliver(message.params);
    if (message.method === 'ui/notifications/host-context-changed') onContext(message.params || {});
    if (message.method === 'ui/resource-teardown') {
      if (message.id !== undefined) post({ id: message.id, result: {} });
      dispose();
    }
  }
  function globals(event) {
    const data = event.detail?.globals || {};
    onContext(data);
    if (data.toolOutput) deliver({ structuredContent: data.toolOutput });
  }
  function dispose() {
    closed = true;
    window.removeEventListener('message', receive);
    window.removeEventListener('openai:set_globals', globals);
    for (const p of pending.values()) {
      clearTimeout(p.timer);
      p.reject(apiError({ errorCode: 'panel_closed' }));
    }
    pending.clear();
  }
  async function start() {
    if (preview) {
      ready = true;
      return;
    }
    if (connecting) return connecting;
    connecting = Promise.resolve()
      .then(async () => {
        window.addEventListener('message', receive);
        window.addEventListener('openai:set_globals', globals);
        if (window.openai?.toolOutput) deliver({ structuredContent: window.openai.toolOutput });
        return request('ui/initialize', {
          protocolVersion: '2026-01-26',
          appInfo: { name: 'Codex Trace', version: VERSION },
          appCapabilities: {},
        });
      })
      .then(async (result) => {
        if (result.protocolVersion !== '2026-01-26')
          throw apiError({ errorCode: 'unsupported_host' });
        ready = true;
        onContext(result.hostContext || {});
        post({ method: 'ui/notifications/initialized' });
        // Reopening a sidebar does not require a new model turn or tool-result notification.
        if (!receivedLaunch) {
          try {
            const initial = await request('tools/call', {
              name: 'open_rollout_viewer',
              arguments: {},
            });
            if (!receivedLaunch) {
              if (initial.isError || initial.structuredContent?.error)
                throw apiError(
                  initial.structuredContent,
                  initial.content?.find((item) => item.type === 'text')?.text,
                );
              deliver(initial);
            }
          } catch (error) {
            if (!receivedLaunch) throw error;
          }
        }
      })
      .catch((error) => {
        onError(error);
        throw error;
      });
    return connecting;
  }
  return {
    preview,
    start,
    dispose,
    async call(name, args = {}) {
      if (closed) throw apiError({ errorCode: 'panel_closed' });
      let result;
      if (preview) {
        const response = await fetch('/api', {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, arguments: args }),
        });
        result = await response.json();
        if (!response.ok) throw apiError(result);
      } else {
        if (!ready) await start();
        result = await request('tools/call', { name, arguments: args });
      }
      if (result.isError || result.structuredContent?.error)
        throw apiError(
          result.structuredContent,
          result.content?.find((x) => x.type === 'text')?.text,
        );
      return result.structuredContent || result;
    },
  };
}
