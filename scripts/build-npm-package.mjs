import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { buildPlugin } from './build-plugin.mjs';

await buildPlugin({ check: true });
execFileSync('python3', [fileURLToPath(new URL('./build-npm-package.py', import.meta.url))], {
  cwd: path.resolve(fileURLToPath(new URL('..', import.meta.url))),
  stdio: 'inherit',
});
