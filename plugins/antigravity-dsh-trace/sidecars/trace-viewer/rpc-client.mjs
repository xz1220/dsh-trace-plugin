import {spawn} from 'node:child_process';

// One backend process serves all panes; request IDs, not callback order, pair
// responses with requests. A failed process never leaves UI calls pending.
export class McpClient {
  constructor({command = 'python3', args, cwd, env = process.env, timeoutMs = 16000} = {}) {
    this.options = {command, args, cwd, env, timeoutMs};
    this.pending = new Map();
    this.counter = 0;
    this.child = null;
    this.starting = null;
    this.closed = false;
    this.buffer = '';
  }

  async start() {
    if (this.closed) throw new Error('The trace reader is closed.');
    if (this.starting) return this.starting;
    const {command, args, cwd, env} = this.options;
    const child = spawn(command, args, {cwd, env, stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true});
    this.child = child;
    child.stdout.setEncoding('utf8');
    child.stdout.on('data', chunk => {if (this.child === child) this.receive(chunk);});
    // Backend diagnostics stay out of RPC stdout and of the rendered trace.
    child.stderr.on('data', () => {});
    child.on('error', () => {if (this.child === child) this.fail(new Error('Unable to start the trace reader.'));});
    child.on('exit', () => {if (this.child === child) this.fail(new Error('The trace reader stopped. Retry the operation.'));});
    child.stdin.on('error', () => {if (this.child === child) this.fail(new Error('The trace reader connection closed.'));});
    this.starting = this.send('initialize', {protocolVersion: '2025-06-18', capabilities: {}, clientInfo: {name: 'antigravity-dsh-trace', version: '0.2.19'}}).then(() => {
      this.write({jsonrpc: '2.0', method: 'notifications/initialized'});
    }).catch(error => {if (this.child === child) this.fail(error); throw error;});
    return this.starting;
  }

  write(message) {
    if (!this.child || this.child.stdin.destroyed) throw new Error('The trace reader connection closed.');
    this.child.stdin.write(JSON.stringify(message) + '\n');
  }

  send(method, params) {
    const id = ++this.counter;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error('Reading the execution trace timed out. Retry the operation.'));
      }, this.options.timeoutMs);
      this.pending.set(id, {resolve, reject, timer});
      try { this.write({jsonrpc: '2.0', id, method, params}); }
      catch (error) { clearTimeout(timer); this.pending.delete(id); reject(error); }
    });
  }

  receive(chunk) {
    this.buffer += chunk;
    if (this.buffer.length > 32 * 1024 * 1024) {
      this.fail(new Error('The trace reader returned an oversized response.'));
      return;
    }
    let newline;
    while ((newline = this.buffer.indexOf('\n')) !== -1) {
      const line = this.buffer.slice(0, newline);
      this.buffer = this.buffer.slice(newline + 1);
      let message;
      try { message = JSON.parse(line); }
      catch { this.fail(new Error('The trace reader returned an invalid response.')); return; }
      const pending = message.jsonrpc === '2.0' ? this.pending.get(message.id) : null;
      if (!pending) continue;
      this.pending.delete(message.id);
      clearTimeout(pending.timer);
      if (message.error) pending.reject(new Error(message.error.message || 'Unable to read this execution trace.'));
      else pending.resolve(message.result);
    }
  }

  fail(error) {
    for (const request of this.pending.values()) {
      clearTimeout(request.timer);
      request.reject(error);
    }
    this.pending.clear();
    const child = this.child;
    this.child = null;
    this.starting = null;
    this.buffer = '';
    child?.kill();
  }

  async call(params) {
    await this.start();
    if (this.closed) throw new Error('The trace reader connection closed.');
    if (this.pending.size >= 32) throw new Error('Too many trace requests are in progress. Retry shortly.');
    return this.send('tools/call', params);
  }

  close() {
    this.closed = true;
    this.fail(new Error('The trace pane closed.'));
  }
}
