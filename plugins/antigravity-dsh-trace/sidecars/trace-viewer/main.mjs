import {readFileSync} from 'node:fs';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {SidecarApp, Response} from 'sidecar_sdk';
import {McpClient} from './rpc-client.mjs';
import {makeToolRequest} from './tool-request.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '../..');
const app = new SidecarApp();
const reader = new McpClient({
  command: process.env.ANTIGRAVITY_DSH_PYTHON || 'python3',
  args: ['-u', join(root, 'server/main.py')],
  cwd: root,
});
const noCache = {'Cache-Control': 'no-store'};

app.page('/', () => new Response(readFileSync(join(here, 'host.html'), 'utf8'), {contentType: 'text/html; charset=utf-8', headers: noCache}));
app.page('/host.js', () => new Response(readFileSync(join(here, 'host.js'), 'utf8'), {contentType: 'application/javascript; charset=utf-8', headers: noCache}));
app.page('/viewer', () => new Response(readFileSync(join(root, 'assets/viewer.html'), 'utf8'), {contentType: 'text/html; charset=utf-8', headers: noCache}));
app.api('/api/rpc', async data => {
  try {
    return await reader.call(makeToolRequest(data));
  } catch (error) {
    const message = error.message || 'Unable to read this execution trace.';
    return {isError: true, content: [{type: 'text', text: message}], structuredContent: {error: message}};
  }
});

let stopping = false;
async function stop() {
  if (stopping) return;
  stopping = true;
  reader.close();
  await app.close();
}
process.once('SIGTERM', stop);
process.once('SIGINT', stop);
process.once('exit', () => reader.close());
await app.run();
