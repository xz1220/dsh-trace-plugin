import { test as base, expect } from '@playwright/test';
import { spawn } from 'node:child_process';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createInterface } from 'node:readline';

export const test = base.extend({
  recordingServer: [
    async ({}, use) => {
      const directory = await mkdtemp(path.join(tmpdir(), 'codex-trace-e2e-'));
      const child = spawn(
        process.env.PYTHON || 'python3',
        ['scripts/demo.py', '--directory', directory],
        { stdio: ['ignore', 'pipe', 'pipe'] },
      );
      let errors = '';
      child.stderr.on('data', (chunk) => {
        errors += chunk;
      });
      try {
        const url = await new Promise((resolve, reject) => {
          const timer = setTimeout(
            () => reject(new Error(`Demo startup timed out: ${errors}`)),
            20000,
          );
          const lines = createInterface({ input: child.stdout });
          lines.on('line', (line) => {
            try {
              const value = JSON.parse(line);
              if (value.url) {
                clearTimeout(timer);
                lines.close();
                resolve(value.url);
              }
            } catch {
              /* Other output is not a launch record. */
            }
          });
          child.once('exit', (code) => {
            clearTimeout(timer);
            reject(new Error(`Demo exited (${code}): ${errors}`));
          });
          child.once('error', (error) => {
            clearTimeout(timer);
            reject(error);
          });
        });
        await use({ url, directory });
      } finally {
        child.kill('SIGTERM');
        await new Promise((resolve) =>
          child.exitCode !== null || child.signalCode !== null
            ? resolve()
            : child.once('exit', resolve),
        );
        await rm(directory, { recursive: true, force: true });
      }
    },
    { scope: 'worker' },
  ],
});
export { expect };
