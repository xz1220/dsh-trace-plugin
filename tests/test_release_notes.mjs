import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';

const execute = promisify(execFile);
const script = fileURLToPath(new URL('../scripts/release-notes.mjs', import.meta.url));

test('release notes select the package version from release-please linked headings', async (t) => {
  const directory = await mkdtemp(path.join(tmpdir(), 'codex-trace-release-notes-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  await writeFile(path.join(directory, 'package.json'), JSON.stringify({ version: '1.2.3' }));
  await writeFile(
    path.join(directory, 'CHANGELOG.md'),
    '# Changelog\n\n## Unreleased\n\nFuture work.\n\n## [1.2.3](https://example.com/compare) (2026-11-16)\n\n### Fixed\n\n- A reviewed fix.\n\n## 1.2.2\n\nAn older release.\n',
  );
  const { stdout } = await execute(process.execPath, [script], { cwd: directory });
  assert.match(stdout, /^## \[1\.2\.3\]/);
  assert.match(stdout, /A reviewed fix/);
  assert.doesNotMatch(stdout, /Future work|An older release/);
});

test('release notes fail when the current version is missing instead of using older notes', async (t) => {
  const directory = await mkdtemp(path.join(tmpdir(), 'codex-trace-release-notes-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  await writeFile(path.join(directory, 'package.json'), JSON.stringify({ version: '1.2.3' }));
  await writeFile(path.join(directory, 'CHANGELOG.md'), '# Changelog\n\n## 1.2.2\n\nOld notes.\n');
  await assert.rejects(execute(process.execPath, [script], { cwd: directory }), (error) => {
    assert.match(error.stderr, /no release entry for 1\.2\.3/);
    assert.equal(error.stdout, '');
    return true;
  });
});
