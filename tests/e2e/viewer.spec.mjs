import { test, expect } from './server.mjs';
import AxeBuilder from '@axe-core/playwright';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

const execute = promisify(execFile);

test('cold load, request inspection, search and persisted duration', async ({
  page,
  recordingServer,
}) => {
  await page.goto(recordingServer.url);
  await expect(page.getByRole('searchbox')).toBeVisible();
  await expect(
    page.getByText('Inspect code, tools and images.', { exact: false }).first(),
  ).toBeVisible();
  const request = page.getByRole('button', { name: '请求 #1', exact: true });
  await request.focus();
  await expect(request).toBeFocused();
  await page.keyboard.press('Enter');
  await page.getByRole('tab', { name: '完整上下文', exact: true }).click();
  await expect(page.getByRole('button', { name: '复制完整上下文', exact: true })).toBeVisible();
  await expect(
    page.getByText('You are reviewing a synthetic recording.', { exact: false }).first(),
  ).toBeVisible();
  if (process.env.UPDATE_DOC_SCREENSHOT) {
    await page.screenshot({ path: 'docs/images/trace-viewer.png' });
  }
  await page.getByRole('tab', { name: '原始请求', exact: true }).click();
  await expect(page.getByRole('tabpanel', { name: '原始请求', exact: true })).toContainText(
    'review-model',
  );
  await page.getByRole('button', { name: '关闭详情', exact: true }).click();
  await page.getByRole('searchbox').fill('SCHEMA_SEARCH_MARKER');
  await expect(page.getByRole('status').filter({ hasText: '匹配' })).toContainText(
    /[1-9]\d* 条匹配/,
  );
  await page.getByRole('searchbox').fill('');
  const duration = page.getByRole('button', { name: '使用实际时长', exact: true });
  await duration.click();
  const pressed = await duration.getAttribute('aria-pressed');
  await page.reload();
  await expect(duration).toHaveAttribute('aria-pressed', pressed);
});

test('native bridge follows host locale/theme, narrow layout and accessibility', async ({
  page,
  recordingServer,
}) => {
  await page.goto(recordingServer.url);
  await page.goto(new URL('/harness?cold=1', recordingServer.url).href);
  const viewer = page.frameLocator('iframe');
  await expect(viewer.getByRole('searchbox')).toBeVisible();
  const light = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
    .analyze();
  expect(light.violations).toEqual([]);
  await page.evaluate(() =>
    document.querySelector('iframe').contentWindow.postMessage(
      {
        jsonrpc: '2.0',
        method: 'ui/notifications/host-context-changed',
        params: { theme: 'dark', locale: 'en-US' },
      },
      location.origin,
    ),
  );
  await expect(viewer.locator('html')).toHaveAttribute('lang', 'en');
  await expect(viewer.locator('body')).toHaveAttribute('data-ds-dark-theme', '');
  await page.setViewportSize({ width: 360, height: 760 });
  const frame = page.frames().find((frame) => frame.url().endsWith('/native-frame'));
  await frame.evaluate(async () => {
    await Promise.all(
      document.getAnimations().map((animation) => animation.finished.catch(() => {})),
    );
  });
  expect(await frame.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  // Scan the real inner app. iframe inclusion is handled by axe in the host document.
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
    .analyze();
  expect(results.violations).toEqual([]);
});

test('live append appears automatically without losing recorded history', async ({
  page,
  recordingServer,
}) => {
  await page.goto(recordingServer.url);
  // Exercise the app-only launch path through the real HTTP transport.
  await page.addInitScript(() => {
    let preview;
    Object.defineProperty(window, '__ROLLOUT_PREVIEW__', {
      configurable: true,
      get: () => preview,
      set: (value) => {
        preview = { ...value, traceId: 'review-live' };
      },
    });
  });
  await page.reload();
  await expect(
    page.getByText('Watch the controlled live append.', { exact: false }).first(),
  ).toBeVisible();
  await execute(process.env.PYTHON || 'python3', [
    'scripts/review-fixtures.py',
    '--output',
    recordingServer.directory,
    '--reset-live',
  ]);
  await execute(process.env.PYTHON || 'python3', [
    'scripts/review-fixtures.py',
    '--output',
    recordingServer.directory,
    '--advance-live',
  ]);
  await expect(page.getByText('Live append completed.', { exact: false }).first()).toBeVisible({
    timeout: 12000,
  });
  await expect(
    page.getByText('Watch the controlled live append.', { exact: false }).first(),
  ).toBeVisible();
});
