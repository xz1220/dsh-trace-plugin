import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, copyFileSync, writeFileSync, realpathSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const source = fileURLToPath(
  new URL('../packages/dsh-trace-extension/bin/dsh-trace-extension.mjs', import.meta.url),
);

function fixture(t) {
  const root = realpathSync(mkdtempSync(path.join(tmpdir(), 'dsh-npm-cli-')));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  mkdirSync(path.join(root, 'bin'));
  mkdirSync(path.join(root, 'payload/installer'), { recursive: true });
  copyFileSync(source, path.join(root, 'bin/cli.mjs'));
  writeFileSync(
    path.join(root, 'package.json'),
    JSON.stringify({ name: 'dsh-trace-extension', version: '1.2.3', type: 'module' }),
  );
  writeFileSync(path.join(root, 'payload/bundle-manifest.json'), '{}');
  writeFileSync(path.join(root, 'payload/installer/setup.py'), '# bundled helper fixture\n');
  const runtime = path.join(root, 'python with spaces');
  writeFileSync(
    runtime,
    `#!${process.execPath}\nif(process.argv[2]==='-c')process.exit(process.env.CLI_TEST_OLD?'1':0);console.log(JSON.stringify({args:process.argv.slice(2),home:process.env.HOME}));process.exit(Number(process.env.CLI_TEST_EXIT||0));\n`,
    { mode: 0o700 },
  );
  return {
    root,
    run(args, extra = {}) {
      return spawnSync(process.execPath, [path.join(root, 'bin/cli.mjs'), ...args], {
        encoding: 'utf8',
        cwd: root,
        env: { ...process.env, HOME: root, PATH: '', DSH_TRACE_PYTHON: runtime, ...extra },
      });
    },
  };
}

test('npm CLI forwards setup arguments and the packaged payload without a shell', (t) => {
  const f = fixture(t);
  const trace = path.join(f.root, 'recording data');
  const result = f.run(['setup', '--dry-run', '--trace-root', trace]);
  assert.equal(result.status, 0, result.stderr);
  const output = JSON.parse(result.stdout);
  assert.deepEqual(output.args, [
    path.join(f.root, 'payload/installer/setup.py'),
    'setup',
    '--dry-run',
    '--trace-root',
    trace,
    '--bundle',
    path.join(f.root, 'payload'),
  ]);
  assert.equal(output.home, f.root);
});

test('help and version work without Python or a built payload', (t) => {
  const f = fixture(t);
  rmSync(path.join(f.root, 'payload'), { recursive: true });
  const help = f.run(['--help'], { DSH_TRACE_PYTHON: '/missing-python' });
  assert.equal(help.status, 0);
  assert.match(help.stdout, /npx dsh-trace-extension/);
  const version = f.run(['--version'], { DSH_TRACE_PYTHON: '/missing-python' });
  assert.equal(version.status, 0);
  assert.equal(version.stdout.trim(), '1.2.3');
});

test('missing payload fails locally instead of fetching GitHub', (t) => {
  const f = fixture(t);
  rmSync(path.join(f.root, 'payload'), { recursive: true });
  const result = f.run(['setup', '--json']);
  assert.equal(result.status, 1);
  assert.match(JSON.parse(result.stdout).error, /payload is missing/);
});

test('an explicitly selected incompatible Python is not replaced', (t) => {
  const f = fixture(t);
  const result = f.run(['setup', '--json'], { CLI_TEST_OLD: '1' });
  assert.equal(result.status, 1);
  assert.match(JSON.parse(result.stdout).error, /Python 3.9/);
});

test('doctor, uninstall and helper failures preserve arguments and exit status', (t) => {
  const f = fixture(t);
  for (const action of ['doctor', 'uninstall']) {
    const result = f.run([action, '--dry-run'], { CLI_TEST_EXIT: '17' });
    assert.equal(result.status, 17);
    assert.equal(JSON.parse(result.stdout).args[1], action);
  }
});

test('automatic Python discovery does not execute binaries from an empty or relative PATH entry', (t) => {
  const f = fixture(t);
  const marker = path.join(f.root, 'unexpected-python-run');
  writeFileSync(
    path.join(f.root, 'python3'),
    `#!${process.execPath}\nimport fs from 'node:fs';fs.writeFileSync(${JSON.stringify(marker)},'ran');\n`,
    { mode: 0o700 },
  );
  for (const value of ['', '.']) {
    const result = f.run(['setup', '--json'], { DSH_TRACE_PYTHON: '', PATH: value });
    assert.equal(result.status, 1);
    assert.match(JSON.parse(result.stdout).error, /Python 3.9/);
  }
  assert.throws(() => realpathSync(marker), /ENOENT/);
});
