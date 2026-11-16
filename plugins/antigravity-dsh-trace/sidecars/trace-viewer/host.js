/* Native Antigravity sidecar -> the shared MCP Apps viewer. */
(() => {
  const frame = document.getElementById('viewer');
  const requests = new Set();
  const conversationId = window.sidecar?.conversationId || new URLSearchParams(location.search).get('conversationId') || '';
  let initialized = false, disposed = false;
  let locale = navigator.language || 'en';
  let colorScheme = matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  let themeHint = null;

  function theme() {
    if (themeHint) return themeHint;
    const value = getComputedStyle(document.documentElement).getPropertyValue('--background').trim();
    if (!value) return colorScheme;
    const probe = document.createElement('span');
    probe.style.cssText = 'position:absolute;visibility:hidden;color:var(--background)';
    document.documentElement.appendChild(probe);
    const color = getComputedStyle(probe).color;
    probe.remove();
    // Computed colors can remain oklch/oklab/display-p3. Let the browser's
    // color engine convert them to sRGB instead of treating their components
    // as RGB bytes. A one-pixel canvas is never attached to the page.
    try {
      const canvas = document.createElement('canvas');
      canvas.width = canvas.height = 1;
      const paint = canvas.getContext('2d', {willReadFrequently: true});
      if (paint) {
        paint.fillStyle = color;
        paint.fillRect(0, 0, 1, 1);
        const [r, g, b, a] = paint.getImageData(0, 0, 1, 1).data;
        if (a > 0) {
          const alpha = a / 255;
          const backdrop = colorScheme === 'dark' ? 0 : 255;
          const brightness = alpha * (0.2126 * r + 0.7152 * g + 0.0722 * b) + (1 - alpha) * backdrop;
          colorScheme = brightness < 127.5 ? 'dark' : 'light';
        }
      }
    } catch {
      // Preserve the last host/OS scheme if a restricted host disables canvas.
    }
    return colorScheme;
  }

  function context() {
    return {theme: theme(), locale, displayMode: 'fullscreen'};
  }
  function send(value) {
    if (!disposed) frame.contentWindow?.postMessage({jsonrpc: '2.0', ...value}, location.origin);
  }
  function changed() {
    const scheme = theme();
    if (document.documentElement.style.colorScheme !== scheme) document.documentElement.style.colorScheme = scheme;
    if (initialized) send({method: 'ui/notifications/host-context-changed', params: context()});
  }

  async function invoke(params) {
    if (!params || typeof params.name !== 'string' || !params.arguments || typeof params.arguments !== 'object' || Array.isArray(params.arguments)) {
      throw new Error('Invalid viewer request.');
    }
    const controller = new AbortController();
    requests.add(controller);
    const timer = setTimeout(() => controller.abort(), 18000);
    try {
      const response = await window.sidecar.fetch('/api/rpc', {
        method: 'POST', signal: controller.signal,
        body: JSON.stringify({name: params.name, arguments: params.arguments, conversationId}),
      });
      if (!response.ok) throw new Error(`Unable to read the execution trace (${response.status}).`);
      return await response.json();
    } finally {
      clearTimeout(timer);
      requests.delete(controller);
    }
  }

  async function receive(event) {
    // Only the embedded viewer may invoke its reader. Host notifications come
    // from Antigravity's parent, never from another sidecar or sibling frame.
    if (event.source === window.parent && event.source !== frame.contentWindow) {
      if (event.data?.type === 'theme-change') {
        const payload = event.data.payload || {};
        if (typeof payload.locale === 'string') locale = payload.locale;
        themeHint = ['light', 'dark'].includes(payload.theme) ? payload.theme : null;
        if (themeHint) colorScheme = themeHint;
        changed();
      }
      return;
    }
    if (event.source !== frame.contentWindow || event.origin !== location.origin || event.data?.jsonrpc !== '2.0' || disposed) return;
    const message = event.data;
    if (message.method === 'ui/initialize') {
      send({id: message.id, result: {protocolVersion: '2026-01-26', hostInfo: {name: 'Antigravity', version: 'sidecar'}, hostCapabilities: {}, hostContext: context()}});
    } else if (message.method === 'ui/notifications/initialized') {
      initialized = true;
    } else if (message.method === 'ping') {
      send({id: message.id, result: {}});
    } else if (message.method === 'tools/call') {
      try { send({id: message.id, result: await invoke({...message.params, arguments: message.params?.arguments || {}})}); }
      catch (error) { send({id: message.id, error: {code: -32603, message: error.name === 'AbortError' ? 'Reading the execution trace timed out. Retry the operation.' : error.message}}); }
    } else if (message.id !== undefined && message.method) {
      send({id: message.id, error: {code: -32601, message: 'Unsupported viewer operation.'}});
    }
  }

  window.addEventListener('message', receive);
  const observer = new MutationObserver(changed);
  observer.observe(document.documentElement, {attributes: true, attributeFilter: ['style']});
  window.addEventListener('languagechange', () => {locale = navigator.language || 'en'; changed();});
  window.addEventListener('pagehide', () => {
    send({id: 'antigravity-teardown', method: 'ui/resource-teardown', params: {}});
    disposed = true;
    observer.disconnect();
    window.removeEventListener('message', receive);
    for (const controller of requests) controller.abort();
    requests.clear();
  }, {once: true});
})();
