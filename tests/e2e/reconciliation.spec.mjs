import { test as base, expect } from '@playwright/test';
import { execFile, spawn } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';

const execute = promisify(execFile);
const root = fileURLToPath(new URL('../..', import.meta.url));
const python = process.env.PYTHON || 'python3';
const commandOptions = {
  cwd: root,
  env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
};

const test = base.extend({
  reconciliationServer: async ({}, use, testInfo) => {
    // The shared synthetic case is owned by this test's artifact directory.
    const directory = testInfo.outputPath('fixture');
    await mkdir(directory, { recursive: true });
    await execute(
      python,
      ['scripts/reconcile.py', 'fixture', '--output', directory],
      commandOptions,
    );
    const child = spawn(
      python,
      ['scripts/reconcile.py', 'serve', '--fixture', directory, '--port', '0'],
      { ...commandOptions, stdio: ['ignore', 'pipe', 'pipe'] },
    );
    let errors = '';
    child.stderr.on('data', (chunk) => {
      errors = (errors + chunk).slice(-12000);
    });
    try {
      const url = await new Promise((resolve, reject) => {
        const lines = createInterface({ input: child.stdout });
        const timer = setTimeout(() => {
          lines.close();
          reject(new Error(`Reconciliation preview startup timed out: ${errors}`));
        }, 20000);
        lines.on('line', (line) => {
          try {
            const value = JSON.parse(line);
            if (value.url) {
              clearTimeout(timer);
              lines.close();
              resolve(value.url);
            }
          } catch {
            // Only the launch JSON is part of this small CLI contract.
          }
        });
        child.once('exit', (code) => {
          clearTimeout(timer);
          lines.close();
          reject(new Error(`Reconciliation preview exited (${code}): ${errors}`));
        });
        child.once('error', (error) => {
          clearTimeout(timer);
          lines.close();
          reject(error);
        });
      });
      await use({ url, directory });
    } finally {
      if (child.exitCode === null && child.signalCode === null) {
        child.kill('SIGTERM');
        await new Promise((resolve) => child.once('exit', resolve));
      }
    }
  },
});

async function expectToolOutput(viewer, marker) {
  const row = viewer.locator('tr[data-kind="tool"]').filter({ hasText: marker });
  await expect(row).toHaveCount(1);
  await row.click();
  await viewer.getByRole('tab', { name: '结果', exact: true }).click();
  // A command argument can contain the marker too. Read only the result body's pre,
  // preserving its stdout newline, rather than matching text elsewhere in the app.
  const output = viewer.getByRole('region', { name: '渲染结果', exact: true }).locator('pre');
  await expect(output).toHaveCount(1);
  await expect.poll(() => output.textContent()).toBe(`${marker}\n`);
  await viewer.getByRole('button', { name: '关闭详情', exact: true }).click();
}

async function expectFinalReply(viewer, marker) {
  const row = viewer.locator('tr[data-kind="message"]').filter({ hasText: marker });
  await expect(row).toHaveCount(1);
  await expect.poll(() => row.locator('td').nth(1).textContent()).toBe(marker);
  await row.click();
  await viewer.getByRole('tab', { name: '原始内容', exact: true }).click();
  const content = viewer.getByRole('tabpanel', { name: '原始内容', exact: true }).locator('pre');
  await expect(content).toHaveCount(1);
  await expect.poll(() => content.textContent()).toBe(marker);
  await viewer.getByRole('button', { name: '关闭详情', exact: true }).click();
}

test('built viewer reconciles A output/final and appends delegated B while preserving A', async ({
  page,
  reconciliationServer,
}) => {
  const { url, directory } = reconciliationServer;
  const traceFile = path.join(directory, 'capture/trace.jsonl');
  const phaseAPrefix = await readFile(traceFile);
  const chatA = JSON.parse(await readFile(path.join(directory, 'chat.json'), 'utf8'));
  const bridgeRequests = [];
  const harness = new URL('/harness?cold=1', url).href;
  expect((await page.request.get(harness)).status()).toBe(403);
  await page.goto(url);
  await expect(page.getByRole('searchbox')).toBeVisible();
  page.on('request', (request) => {
    if (!request.url().endsWith('/api')) return;
    const body = request.postDataJSON();
    if (body?._meta) bridgeRequests.push({ name: body.name, threadId: body._meta.threadId });
  });
  await page.goto(harness);
  const viewer = page.frameLocator('iframe[title="Codex Trace native bridge"]');
  await expect(viewer.getByRole('searchbox')).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.bridgeCalls)).toContain('open_rollout_viewer');

  const finalA = viewer.locator('tr[data-kind="message"]').filter({ hasText: 'RECONCILE_A' });
  await expectFinalReply(viewer, 'RECONCILE_A');
  await expectToolOutput(viewer, 'RECONCILE_A');
  await expect(
    viewer.locator('tr[data-kind="message"]').filter({ hasText: 'RECONCILE_B' }),
  ).toHaveCount(0);

  await execute(
    python,
    ['scripts/reconcile.py', 'fixture', '--output', directory, '--append-b'],
    commandOptions,
  );
  const phaseAB = await readFile(traceFile);
  expect(phaseAB.subarray(0, phaseAPrefix.length).equals(phaseAPrefix)).toBe(true);
  expect(phaseAB.length).toBeGreaterThan(phaseAPrefix.length);
  const finalB = viewer.locator('tr[data-kind="message"]').filter({ hasText: 'RECONCILE_B' });
  await expect(finalB).toHaveCount(1, { timeout: 12000 });
  await expect(finalA).toHaveCount(1);
  await expectFinalReply(viewer, 'RECONCILE_B');
  await expectFinalReply(viewer, 'RECONCILE_A');
  await expectToolOutput(viewer, 'RECONCILE_B');
  await expectToolOutput(viewer, 'RECONCILE_A');
  await expect(finalA).toHaveCount(1);
  await expect(finalB).toHaveCount(1);
  // B was delivered by a tool; the app must not invent a plain user row for it.
  await expect(
    viewer.locator('tr[data-kind="user"]').filter({ hasText: 'RECONCILE_B' }),
  ).toHaveCount(0);
  const bridgeCalls = await page.evaluate(() => window.bridgeCalls);
  expect(bridgeCalls).toEqual(
    expect.arrayContaining([
      'ui/initialize',
      'ui/notifications/initialized',
      'open_rollout_viewer',
    ]),
  );
  expect(bridgeRequests.length).toBeGreaterThan(0);
  expect(bridgeRequests.every((request) => request.threadId === chatA.thread.id)).toBe(true);
  await writeFile(
    test.info().outputPath('ui-evidence.json'),
    JSON.stringify(
      {
        evidence: 'authenticated headless preview with MCP bridge harness; not native desktop',
        threadId: chatA.thread.id,
        phaseAPrefixBytes: phaseAPrefix.length,
        phaseAPrefixPreserved: true,
        bridgeCalls,
        bridgeRequests,
        exactRenderedStdout: ['RECONCILE_A\n', 'RECONCILE_B\n'],
        exactFinalRawContent: ['RECONCILE_A', 'RECONCILE_B'],
        stdoutNormalization: 'none; textContent includes the recorded trailing newline',
        finalNormalization: 'none; raw-content pre textContent equals the final reply',
      },
      null,
      2,
    ) + '\n',
  );
  await page.screenshot({ path: test.info().outputPath('synthetic-ab.png') });
});
