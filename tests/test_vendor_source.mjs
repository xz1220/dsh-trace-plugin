import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { verifyVendorSource } from '../scripts/vendor-source.mjs';

async function checkout(t) {
  const directory = await mkdtemp(path.join(tmpdir(), 'codex-trace-vendor-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const git = (...args) =>
    execFileSync('git', ['-C', directory, ...args], { encoding: 'utf8' }).trim();
  git('init', '--quiet');
  await writeFile(path.join(directory, 'source.ts'), 'export const value = 1;\n');
  git('add', '--', 'source.ts');
  git(
    '-c',
    'user.name=Vendor test',
    '-c',
    'user.email=vendor-test@example.invalid',
    '-c',
    'commit.gpgsign=false',
    'commit',
    '--quiet',
    '-m',
    'test source',
  );
  return { directory, pin: { repository: 'test/upstream', commit: git('rev-parse', 'HEAD') } };
}

test('a clean checkout of the pinned commit works without an origin remote', async (t) => {
  const { directory, pin } = await checkout(t);
  assert.deepEqual(verifyVendorSource(directory, pin), pin);
});

test('a different commit is rejected before importing source', async (t) => {
  const { directory, pin } = await checkout(t);
  assert.throws(
    () => verifyVendorSource(directory, { ...pin, commit: '0'.repeat(40) }),
    /Vendor source must be test\/upstream@/,
  );
});

test('tracked modifications and untracked files both invalidate provenance', async (t) => {
  const { directory, pin } = await checkout(t);
  await writeFile(path.join(directory, 'source.ts'), 'export const value = 2;\n');
  assert.throws(() => verifyVendorSource(directory, pin), /must be clean/);
  await writeFile(path.join(directory, 'source.ts'), 'export const value = 1;\n');
  await writeFile(path.join(directory, 'new.ts'), 'export const extra = true;\n');
  assert.throws(() => verifyVendorSource(directory, pin), /must be clean/);
});

test('a nested directory cannot masquerade as the checkout root', async (t) => {
  const { directory, pin } = await checkout(t);
  const nested = path.join(directory, 'nested');
  await mkdir(nested);
  assert.throws(() => verifyVendorSource(nested, pin), /checkout root/);
});
