import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { updateGeneratedFiles } from '../scripts/generated-files.mjs';
import { versionArtifacts } from '../scripts/sync-version.mjs';
import { VERSION } from '../src/version.js';

test('generated asset checks detect missing and changed files without rewriting them', async (t) => {
  const temporary = await mkdtemp(path.join(tmpdir(), 'codex-trace-generated-'));
  t.after(() => rm(temporary, { recursive: true, force: true }));
  const file = path.join(temporary, 'asset.txt');
  const files = new Map([[file, 'expected content\n']]);
  await assert.rejects(updateGeneratedFiles(files, { check: true }), /Generated files are stale/);
  await assert.rejects(stat(file), { code: 'ENOENT' });
  await updateGeneratedFiles(files);
  await updateGeneratedFiles(files, { check: true });
  await writeFile(file, 'changed content\n');
  await assert.rejects(updateGeneratedFiles(files, { check: true }), /Generated files are stale/);
  assert.equal(await readFile(file, 'utf8'), 'changed content\n');
});

test('frontend and server version metadata derive from the package version', async () => {
  const packageInfo = JSON.parse(await readFile('package.json', 'utf8'));
  const { version, files } = await versionArtifacts();
  assert.equal(version, packageInfo.version);
  assert.equal(VERSION, version);
  assert.equal(
    JSON.parse(files.get('plugins/codex-dsh-trace/.codex-plugin/plugin.json')).version,
    version,
  );
  await updateGeneratedFiles(files, { check: true });
});
