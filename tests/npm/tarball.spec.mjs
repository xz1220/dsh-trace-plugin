import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import {
  mkdtempSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
  rmSync,
  existsSync,
  realpathSync,
  symlinkSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../..', import.meta.url));
const npm =
  process.env.npm_execpath ||
  realpathSync(execFileSync('which', ['npm'], { encoding: 'utf8' }).trim());

test('the real npm tarball is self-contained and survives deletion of the npx cache', (t) => {
  const temp = realpathSync(mkdtempSync(path.join(tmpdir(), 'dsh-npm-package-')));
  t.after(() => rmSync(temp, { recursive: true, force: true }));
  execFileSync(process.execPath, [path.join(root, 'scripts/build-npm-package.mjs')], {
    cwd: root,
    stdio: 'pipe',
  });
  const candidate = path.join(root, 'dist/npm/dsh-trace-extension');
  const packed = JSON.parse(
    execFileSync(
      process.execPath,
      [npm, 'pack', candidate, '--ignore-scripts', '--json', '--pack-destination', temp],
      { cwd: root, encoding: 'utf8' },
    ),
  )[0];
  const files = packed.files.map((f) => f.path);
  assert.ok(files.includes('payload/plugins/codex-dsh-trace/assets/viewer.html'));
  assert.ok(files.includes('payload/installer/setup.py'));
  assert.ok(files.includes('payload/installer/installer_bundle.py'));
  assert.ok(files.includes('payload/.agents/plugins/marketplace.json'));
  assert.ok(files.includes('THIRD_PARTY_NOTICES.txt'));
  assert.ok(
    files.every(
      (f) =>
        ['package.json', 'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.txt'].includes(f) ||
        f.startsWith('bin/') ||
        f.startsWith('payload/'),
    ),
  );
  assert.ok(
    !files.some((f) =>
      f
        .split('/')
        .some((p) =>
          ['.git', '.npmrc', 'node_modules', 'recordings', 'local-context', 'tests'].includes(p),
        ),
    ),
  );
  const metadata = JSON.parse(readFileSync(path.join(candidate, 'package.json'), 'utf8'));
  assert.equal(metadata.private, undefined);
  assert.deepEqual(metadata.dependencies || {}, {});
  assert.equal(metadata.scripts, undefined);
  const home = path.join(temp, 'home'),
    bin = path.join(temp, 'bin');
  const codexHome = path.join(home, '.codex'),
    cache = path.join(temp, 'npm-cache');
  mkdirSync(home);
  mkdirSync(bin);
  symlinkSync('/bin/sh', path.join(bin, 'sh'));
  writeFileSync(path.join(bin, 'package.json'), JSON.stringify({ type: 'module' }));
  const python = execFileSync('python3', ['-c', 'import sys; print(sys.executable)'], {
    encoding: 'utf8',
  }).trim();
  const env = {
    ...process.env,
    HOME: home,
    CODEX_HOME: codexHome,
    CODEX_ROLLOUT_TRACE_ROOT: path.join(codexHome, 'rollout-traces'),
    PATH: bin + path.delimiter + path.dirname(process.execPath),
    DSH_TRACE_PYTHON: python,
  };
  // Only these executable stand-ins are exposed to the real setup process.
  const fake = `#!${process.execPath}
import fs from 'node:fs';import path from 'node:path';
const root=process.env.CODEX_HOME;const file=path.join(root,'fake-system.json');
let state=fs.existsSync(file)?JSON.parse(fs.readFileSync(file,'utf8')):{};
const args=process.argv.slice(2),tool=path.basename(process.argv[1]);let output={},write=false;
if(tool==='launchctl'){
 if(args[0]==='getenv'){if(!state.environment)process.exit(1);console.log(state.environment);process.exit(0)}
 if(args[0]==='setenv'){state.environment=args[2];write=true}
 else if(args[0]==='unsetenv'){delete state.environment;write=true}
 else throw Error('unexpected launchctl command');
}else if(args[0]==='--version'){console.log('codex-cli 0.163.0');process.exit(0)}
else if(args.join(' ')==='plugin add --help'){console.log('plugin add');process.exit(0)}
else if(args.join(' ')==='plugin marketplace list --json'){output={marketplaces:state.marketplace?[state.marketplace]:[]}}
else if(args.join(' ')==='plugin list --marketplace rollout-local --json'){output={installed:state.plugin?[state.plugin]:[],available:[]}}
else if(args[0]==='plugin'&&args[1]==='marketplace'&&args[2]==='add'){
 const source=args[3];if(!fs.existsSync(path.join(source,'.agents/plugins/marketplace.json')))throw Error('unstaged source');
 state.marketplace={name:'rollout-local',root:source,marketplaceSource:{sourceType:'local',source}};write=true;
}else if(args[0]==='plugin'&&args[1]==='add'){
 const source=state.marketplace.root;const catalog=JSON.parse(fs.readFileSync(path.join(source,'.agents/plugins/marketplace.json'),'utf8'));
 const plugin=path.resolve(source,catalog.plugins[0].source.path);const version=JSON.parse(fs.readFileSync(path.join(plugin,'.codex-plugin/plugin.json'),'utf8')).version;
 state.plugin={pluginId:'codex-dsh-trace@rollout-local',installed:true,enabled:true,version};write=true;
}else if(args[0]==='plugin'&&args[1]==='remove'){delete state.plugin;write=true}
else throw Error('unexpected Codex command: '+args.join(' '));
if(write){fs.mkdirSync(root,{recursive:true});fs.writeFileSync(file,JSON.stringify(state))}console.log(JSON.stringify(output));
`;
  for (const name of ['codex', 'launchctl'])
    writeFileSync(path.join(bin, name), fake, { mode: 0o700 });
  const tarball = path.join(temp, packed.filename);
  function npx(args) {
    return spawnSync(
      process.execPath,
      [
        npm,
        'exec',
        '--yes',
        '--offline',
        '--ignore-scripts',
        '--cache',
        cache,
        '--package',
        tarball,
        '--',
        'dsh-trace-extension',
        ...args,
      ],
      { cwd: temp, env, encoding: 'utf8', timeout: 120000 },
    );
  }
  const version = npx(['--version']);
  assert.equal(version.status, 0, version.stderr);
  assert.equal(version.stdout.trim(), metadata.version);
  const help = npx(['--help']);
  assert.equal(help.status, 0, help.stderr);
  assert.match(help.stdout, /no GitHub login/);
  const plan = npx(['setup', '--dry-run', '--json']);
  if (process.platform !== 'darwin') {
    assert.equal(plan.status, 1);
    assert.match(JSON.parse(plan.stdout).error, /macOS/);
    assert.ok(!existsSync(codexHome));
    return;
  }
  assert.equal(plan.status, 0, plan.stderr);
  assert.equal(JSON.parse(plan.stdout).status, 'dry-run');
  assert.ok(!existsSync(codexHome), 'dry-run must not create persistent configuration');
  const setup = npx(['setup', '--yes', '--json']);
  assert.equal(setup.status, 0, setup.stderr + setup.stdout);
  const state = JSON.parse(readFileSync(path.join(codexHome, 'fake-system.json'), 'utf8'));
  assert.equal(state.marketplace.root, path.join(codexHome, 'dsh-trace-extension/marketplace'));
  assert.ok(!state.marketplace.root.startsWith(cache));
  const catalog = JSON.parse(
    readFileSync(path.join(state.marketplace.root, '.agents/plugins/marketplace.json'), 'utf8'),
  );
  const plugin = path.resolve(state.marketplace.root, catalog.plugins[0].source.path);
  const mcp = JSON.parse(readFileSync(path.join(plugin, '.mcp.json'), 'utf8'));
  assert.ok(path.isAbsolute(mcp.mcpServers['rollout-viewer'].command));
  rmSync(cache, { recursive: true, force: true });
  const rpc = spawnSync(
    mcp.mcpServers['rollout-viewer'].command,
    [path.join(plugin, 'server/main.py')],
    {
      cwd: plugin,
      env,
      input:
        JSON.stringify({
          jsonrpc: '2.0',
          id: 1,
          method: 'initialize',
          params: {
            protocolVersion: '2024-11-05',
            capabilities: {},
            clientInfo: { name: 'npm-test', version: '1' },
          },
        }) + '\n',
      encoding: 'utf8',
      timeout: 20000,
    },
  );
  assert.equal(rpc.status, 0, rpc.stderr);
  assert.ok(
    rpc.stdout
      .split('\n')
      .filter(Boolean)
      .some((line) => JSON.parse(line).id === 1),
  );
  const repeat = npx(['setup', '--yes', '--json']);
  assert.equal(repeat.status, 0, repeat.stderr + repeat.stdout);
  assert.equal(JSON.parse(repeat.stdout).status, 'unchanged');
  const doctor = npx(['doctor', '--json']);
  assert.equal(doctor.status, 0, doctor.stderr + doctor.stdout);
  const recordings = path.join(codexHome, 'rollout-traces');
  writeFileSync(path.join(recordings, 'keep.txt'), 'retained');
  const uninstall = npx(['uninstall', '--yes', '--json']);
  assert.equal(uninstall.status, 0, uninstall.stderr + uninstall.stdout);
  assert.equal(readFileSync(path.join(recordings, 'keep.txt'), 'utf8'), 'retained');
  assert.ok(existsSync(state.marketplace.root), 'registered source must not become dangling');
});
