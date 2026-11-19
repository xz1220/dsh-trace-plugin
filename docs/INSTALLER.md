English | [简体中文](INSTALLER.zh-CN.md)

# Installer guide

The repository became public on 2026-11-16, and the first npm release, [`dsh-trace-extension@0.2.19`](https://www.npmjs.com/package/dsh-trace-extension/v/0.2.19), was published on 2026-11-17. Installation and upgrade guarantees use `0.2.19` as the compatibility baseline; earlier internal development installs are not migrated automatically.

## Quick start

Run from a trusted directory outside the source repository:

```sh
npx dsh-trace-extension setup
```

The package bundles the built plugin, installer logic, and licenses. Default setup requires no GitHub login, private repository access, source checkout, or local frontend build.

Requirements:

- **Node.js 20.19+** and `npm`/`npx`.
- **Python 3.9+** (`python3`) for the local MCP reader (launched with `python3 -B` so it does not write `.pyc` bytecode into the plugin install cache).
- A **Codex** client with local plugins, MCP Apps, and official `rollout-trace` recording support.
- Currently supported target: **macOS / Codex**. Other hosts (such as Antigravity) are not yet integrated.

Setup prints the exact plan of files and settings it will touch. After confirmation, it installs a stable local bundle, registers the local marketplace source, adds the plugin, and configures local recording. Fully quit and reopen Codex afterwards, run a new task, and open **Codex Trace** from the conversation's right-panel tools menu.

## rollout-local source conflict

`Marketplace 'rollout-local' uses a different or unknown source` means the selected Codex profile already binds `rollout-local` to another origin (for example, a source checkout). The helper only adopts verifiable managed sources and receipts and will not overwrite a development registration. Moving to a neutral working directory avoids temporary project-level discovery, but does not remove a persistent registration, and `--yes` never bypasses ownership checks.

Inspect current registrations read-only from a trusted directory outside the checkout (do not publish local paths from the output):

```sh
codex plugin marketplace list --json
```

Preserve existing personal source registrations; use a clean profile without that development registration when testing ordinary npm setup. Temporary CLI overrides do not replace an isolated GUI/login environment. Never delete an entire `CODEX_HOME`, recordings, or unrelated settings to work around a conflict.

## Check and uninstall

```sh
npx dsh-trace-extension setup --dry-run
npx dsh-trace-extension doctor
npx dsh-trace-extension uninstall
```

- `--dry-run` inspects the plan without creating persistent configuration or copying plugin files.
- `doctor` performs read-only checks on configuration, managed files, the Codex install cache, and the local backend; it does not treat an existing install or old recording as native panel acceptance.
- `--yes` skips interactive confirmation in non-interactive shells, while keeping all ownership and edit-conflict guards active.
- `--json` emits machine-readable structured output.
- `--codex-home` and `--trace-root` override default paths. By default, setup installs a login LaunchAgent so future macOS login sessions inherit recording settings; pass `--no-persist` to configure only the current login session. You still need to quit and reopen Codex, and startup ordering with auto-launched Codex should be verified in your native environment.

## Terminal animation

Interactive terminals default to a compact progress view showing only the checks, installation actions, verification steps, and next action, with a fixed-width marker column for consistent alignment. Repair explanations, login details, and internal paths stay collapsed until requested; recording notices appear before confirmation only when recording settings actually change. Custom destinations, target changes, unknown actions, and errors are always shown. Enter `d` at the confirmation prompt to expand the full plan (viewing details does not accept it; enter `y` to install), or pass `--verbose` up front. `--dry-run` always prints the full plan, and unchanged owned installs skip confirmation.

Pass `--no-animation` or set `DSH_TRACE_NO_ANIMATION=1` for static output, and `NO_COLOR` to disable color independently. Redirected output, `TERM=dumb`, CI, and `--json` stay plain without animation control codes.

Maintainers can preview synthetic terminal flows from a source checkout without touching personal configuration:

```sh
npm run demo:installer
npm run demo:installer -- --scenario repair
npm run demo:installer -- --scenario unchanged
npm run demo:installer -- --scenario error
npm run demo:installer -- --verbose
```

This preview script is a development tool only and is excluded from the published npm package.

## Updates and recovery

Installation, upgrades, and verifiable repairs use the same command:

```sh
npx dsh-trace-extension@latest setup --dry-run
npx dsh-trace-extension@latest setup
```

Upgrades start from official npm `0.2.19` and support SemVer 2.0 stable and prerelease progressions (such as `0.2.23-rc.1` via `@next`). Receipts from `0.2.19` must match the published payload digest; newer receipts record the original bundle manifest and managed configuration templates to prove ownership. Unrecognized sources, unknown receipt fields, locally edited files, downgrades, or mismatched bytes for the same version stop safely without overwriting user data.

Upgrades stage the new persistent bundle before switching, retain the active bundle plus the immediate previous bundle (up to 2 managed bundles), and safely prune older superseded bundles after the new state is verified (skipping symlinks or directories with unrecognized files). Re-running the same release reuses verified files. Missing managed files in the stable source or Codex install cache can be restored from the matching package; edited files are preserved and reported rather than overwritten. Extra files in the install cache are never silently deleted during repair; upgrades and uninstall stop for review when unexpected files are present. Inside `__pycache__/` of verified owned Python files, bytecode matching the current interpreter or passing read-only PEP 552 header validation for another CPython version is recognized as runtime cache without executing it.

When upgrading from `0.2.19` with missing files in the stable source, if the `0.2.19` receipt, remaining source files, ownership, and intact install cache all verify independently, setup restores the exact original bytes from the cache inside the same transaction before upgrading. It never substitutes newer bytes or fetches old packages over the network.

Before making changes, setup acquires a per-`CODEX_HOME` lock under `~/Library/Caches/dsh-trace-extension/` and records a private write-ahead journal (`operation.json`). Re-running the same version after an interruption displays a recovery plan, rolls back matching partial writes, and resumes cleanly. `doctor` reports interrupted operations along with the version to retry. If the journal, config, or environment changed externally, setup preserves files and stops for manual review.

The resolved Python interpreter path is part of managed installation identity. If the old interpreter disappears, provide a valid Python 3.9+ on `PATH` or pass `DSH_TRACE_PYTHON=/absolute/path/to/python3` and re-run `setup` to re-pin the managed copy and install cache without editing receipts manually.

## Doctor checks

`doctor` reports configuration, managed source integrity, Codex install cache integrity, and a sandboxed backend probe separately; native panel readiness is always reported as unverified. The cache check inspects the actual files of the enabled version rather than trusting CLI metadata alone. Running a different `npx` version than the installed version is not treated as corruption.

Only when managed source, install cache, and interpreter checks pass does `doctor` copy hash-verified server files into a private temporary directory and run an MCP `initialize`/`tools/list` probe with an empty `HOME` and empty trace directory. Staging enforces file count and 128 MiB size limits; the subprocess is capped at 5 seconds and 128 KiB combined output, terminating its process group on limit breach. Modified or untrusted cache files are never executed, real chats are never read, and a successful probe does not prove native sidebar readiness.

## Stable local copy

Codex registers `$CODEX_HOME/dsh-trace-extension/marketplace`, not the ephemeral `npx` cache, so clearing the npm cache does not break the installed plugin. The managed copy pins the absolute Python executable path to reduce GUI `PATH` drift.

Repeat runs verify files and reuse them; foreign sources or user-edited managed files are preserved and reported. Uninstall preserves recordings and unrelated settings, and retains the stable bundle if Codex still references it to avoid a dangling marketplace path.

Recordings can contain prompts, code, tool output, and credentials; review [Security and privacy](../.github/SECURITY.md) before sharing anything.

## Maintainer packaging and verification

The root workspace package stays `private: true`. The installer modules live under `packages/dsh-trace-extension/installer/`, and the standalone npm package is assembled from an explicit allowlist containing only the CLI, installer/check modules, bundle manifest, marketplace, built plugin, icons, and licenses.

```sh
npm ci
npm run build
npm run test:npm
```

`test:npm` validates tarball contents, cache independence, repeat setup, upgrades, recovery, `doctor`, and uninstall using temporary `HOME`/`CODEX_HOME` directories and fake `codex`/`launchctl` shims. It does not replace real npm registry downloads or native Codex acceptance. To freeze a release archive:

```sh
npm run package:npm
npm pack ./dist/npm/dsh-trace-extension --ignore-scripts --pack-destination dist/npm --json
```

The package has zero runtime dependencies, no `install`/`postinstall` lifecycle scripts, and excludes tests, user configuration, recordings, logs, and the source tree. Installation happens only when the user explicitly runs `setup`.

### Verify a local release archive

Maintainers can dry-run a verified `.tgz` archive in an isolated temporary directory without modifying personal CLI config:

```sh
# Replace with the absolute path to a verified release archive
dsh_archive_tgz="/absolute/path/to/dsh-trace-extension-NEW_VERSION.tgz"
(
  dsh_trial_root="$(mktemp -d)" || exit 1
  [ -n "$dsh_trial_root" ] || exit 1
  cd "$dsh_trial_root" || exit 1
  dsh_trial_root="$(pwd -P)" || exit 1
  [ -n "$dsh_trial_root" ] || exit 1
  mkdir -m 700 "$dsh_trial_root/home" || exit 1
  HOME="$dsh_trial_root/home" CODEX_HOME="$dsh_trial_root/codex" \
    npx --yes --offline --ignore-scripts --cache "$dsh_trial_root/npm-cache" \
    --package "$dsh_archive_tgz" -- dsh-trace-extension setup --dry-run \
    --codex-home "$dsh_trial_root/codex" --trace-root "$dsh_trial_root/recordings"
)
```

Note that `--codex-home` and a temporary `HOME` isolate CLI files only, not the macOS GUI login domain; do not drop `--dry-run` assuming full desktop isolation.

### Prerelease and promotion workflow

See [CHANGELOG.md](../CHANGELOG.md) for release history. When publishing a new version (`NEW_VERSION`):

1. **Internal checks**: freeze and verify the archive (`npm run check`, `npm run test:npm`, `npm run test:e2e`, SHA-256 and file list).
2. **Authorized prerelease**: after explicit publication authorization, publish to the `next` dist-tag (`npm publish "/absolute/path/to/dsh-trace-extension-NEW_VERSION.tgz" --tag next --access public --ignore-scripts`, or via the opt-in OIDC release workflow). The `latest` tag remains unchanged.
3. **Real npm and native verification**: test `npx dsh-trace-extension@next setup` in an isolated macOS / Codex test account, verifying the downloaded archive, sidebar rendering, full client restart, and recording after relogin.
4. **Promote to `latest`**: after native verification and explicit promotion authorization, run `npm dist-tag add "dsh-trace-extension@NEW_VERSION" latest` to promote the exact tested archive, then verify `npx dsh-trace-extension setup` in a clean user profile.

## Acknowledgements

Inspired by [morluto/rea](https://github.com/morluto/rea) for self-contained npm distribution, `setup`/`doctor`/`uninstall` lifecycle UX, plan confirmation, ownership protection, and integrity verification (studied at [`552d1c7`](https://github.com/morluto/rea/tree/552d1c7108b99d1c9ec15d8b629ae07dc56d4714), [MIT License](https://github.com/morluto/rea/blob/552d1c7108b99d1c9ec15d8b629ae07dc56d4714/LICENSE)). This project is an independent implementation and copies no REA code.
