import { defineConfig } from '@playwright/test';
import { fileURLToPath } from 'node:url';

const output = fileURLToPath(new URL('../../.cache/playwright', import.meta.url));

export default defineConfig({
  testDir: '.',
  outputDir: `${output}/results`,
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI
    ? [['github'], ['html', { open: 'never', outputFolder: `${output}/report` }]]
    : 'list',
  use: {
    browserName: 'chromium',
    viewport: { width: 1224, height: 820 },
    trace: 'retain-on-failure',
  },
});
