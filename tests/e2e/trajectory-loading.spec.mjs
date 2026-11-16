import { test, expect } from './server.mjs';

test('failed detail hydration waits for retry and completed detail is reused', async ({
  page,
  recordingServer,
}) => {
  let attempts = 0;
  let succeed = false;
  await page.route('**/api', async (route) => {
    const body = route.request().postDataJSON();
    if (
      body.name === 'get_rollout_cell_detail' &&
      body.arguments.rowId === 'request:1' &&
      body.arguments.cellKey === 'input:1'
    ) {
      attempts += 1;
      if (!succeed) {
        await route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({ errorCode: 'local_read_failed' }),
        });
        return;
      }
    }
    await route.continue();
  });
  await page.goto(recordingServer.url);
  const input = page.getByText('Inspect code, tools and images.', { exact: false }).first();
  await input.click();
  await expect(page.getByRole('alert')).toBeVisible();

  // DSH reports the current selection again after view updates. An error must
  // remain stable until the user explicitly asks for another read.
  const duration = page.getByRole('button', { name: '使用实际时长', exact: true });
  await duration.click();
  await duration.click();
  await expect(page.getByRole('alert')).toBeVisible();
  expect(attempts).toBe(1);

  succeed = true;
  await page.getByRole('button', { name: '重试', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.getByRole('tabpanel')).toContainText('Inspect code, tools and images.');
  expect(attempts).toBe(2);

  await page.getByRole('button', { name: '关闭详情', exact: true }).click();
  await input.click();
  await expect(page.getByRole('tabpanel')).toContainText('Inspect code, tools and images.');
  expect(attempts).toBe(2);
});
