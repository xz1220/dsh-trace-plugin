#!/usr/bin/env node
import { accessSync, constants, existsSync, realpathSync } from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const args = process.argv.slice(2);
const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const payload = path.join(packageRoot, 'payload');

function help() {
  console.log(`dsh-trace-extension

Usage: npx dsh-trace-extension [setup|doctor|uninstall] [options]

  setup          Install the bundled plugin and configure recording (default)
  doctor         Check the installation without changing settings
  uninstall      Remove only unchanged, helper-owned settings and files

  --dry-run      Review the exact plan without persistent changes
  --yes          Apply without an interactive confirmation
  --json         Emit a structured result
  --client codex Choose the agent (currently macOS / Codex only)
  --trace-root PATH
  --codex-home PATH
  --no-persist   Configure this login only

Python 3.9+ and a compatible Codex CLI are required. The package includes the
built plugin: no GitHub login, repository clone, or frontend build is needed.
First setup still requires you to fully quit and reopen Codex.
DSH_TRACE_PYTHON may select an existing Python executable.
`);
}

function fail(message) {
  if (args.includes('--json')) console.log(JSON.stringify({ status: 'error', error: message }));
  else console.error(`dsh-trace-extension: ${message}`);
  process.exitCode = 1;
}

function executable(command) {
  const candidates = command.includes(path.sep)
    ? [path.resolve(command)]
    : (process.env.PATH || '')
        .split(path.delimiter)
        .filter((dir) => path.isAbsolute(dir))
        .map((dir) => path.join(dir, command));
  for (const candidate of candidates) {
    try {
      accessSync(candidate, constants.X_OK);
      return realpathSync(candidate);
    } catch {
      // Continue looking in PATH without asking a shell to interpret values.
    }
  }
  return null;
}

function python() {
  const explicit = process.env.DSH_TRACE_PYTHON;
  const names = explicit
    ? [explicit]
    : [
        'python3',
        'python3.14',
        'python3.13',
        'python3.12',
        'python3.11',
        'python3.10',
        'python3.9',
      ];
  for (const name of names) {
    const binary = executable(name);
    if (!binary) continue;
    if (process.platform === 'darwin' && binary === '/usr/bin/python3') {
      const tools = spawnSync('/usr/bin/xcode-select', ['-p'], { stdio: 'ignore' });
      if (tools.status !== 0) continue;
    }
    const check = spawnSync(
      binary,
      ['-c', 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'],
      { stdio: 'ignore', timeout: 10000 },
    );
    if (check.status === 0) return binary;
  }
  return null;
}

if (args.includes('--help') || args.includes('-h')) {
  help();
} else if (args.includes('--version')) {
  const { readFileSync } = await import('node:fs');
  console.log(JSON.parse(readFileSync(path.join(packageRoot, 'package.json'), 'utf8')).version);
} else if (!existsSync(path.join(payload, 'bundle-manifest.json'))) {
  fail(
    'The built package payload is missing. Use the packaged release, not an unbuilt source folder.',
  );
} else {
  const runtime = python();
  if (!runtime) {
    fail('Python 3.9+ was not found. Install Python or set DSH_TRACE_PYTHON, then retry.');
  } else {
    const helper = path.join(payload, 'installer', 'setup.py');
    const invocation = [helper, ...args, '--bundle', payload];
    const result = spawnSync(runtime, invocation, { stdio: 'inherit', env: process.env });
    if (result.error) fail(`Could not start the setup helper: ${result.error.message}`);
    else process.exitCode = result.status ?? 1;
  }
}
