# Contributing to Codex Trace

Bug reports, documentation improvements, and focused patches are welcome. If you only want to install the plugin, start with the [README](../README.md) and `npx dsh-trace-extension setup`; source development is optional. Read the [code of conduct](CODE_OF_CONDUCT.md) and use synthetic data when describing a problem.

## Issues and proposals

Use [GitHub Issues](https://github.com/xz1220/dsh-trace-plugin/issues) to report a problem or discuss a proposal, and [pull requests](https://github.com/xz1220/dsh-trace-plugin/pulls) for changes. Search existing reports first. Include the goal, expected and actual behavior, plugin/client/OS versions, and a minimal synthetic reproduction. Identify screenshots and observations as local preview, MCP Apps harness, or native Codex evidence.

The maintainer makes the main scope, priority, and acceptance decisions. Record the current disposition in the Issue or PR discussion, alongside GitHub's open/closed/merged state:

| Disposition                    | Meaning                                                                                              | Useful next input                                                                  |
| ------------------------------ | ---------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| Needs reproduction / 待复现    | The behavior or compatibility impact has not yet been reproduced or established.                     | Minimal synthetic steps, environment details, and expected versus actual behavior. |
| Confirmed / 已确认             | Reproduction or reviewed evidence establishes the problem or user need.                              | A focused proposal and relevant regression coverage.                               |
| Planned / 计划中               | The maintainer has accepted a scoped change for future work.                                         | Implementation and validation within that scope; no delivery date is implied.      |
| Not planned for now / 暂不处理 | The change is outside current scope, lacks priority, or cannot be supported with available evidence. | A stated reason; new evidence or a narrower proposal may justify revisiting it.    |

These dispositions do not require pre-existing repository labels. Review work according to feedback volume and available maintenance time; no fixed response or repair deadline is promised. A confirmed report does not itself commit the project to a release.

Discuss larger changes in an Issue before implementation: examples include a new host or platform, recording edits or hosted sharing, broad dependency upgrades, and repository-wide restructuring. State the user problem, proposed behavior, data implications, and evidence needed for acceptance.

Do not put vulnerability details, live traces, credentials, or preview bootstrap URLs in a public Issue or PR. If no private route has been confirmed, open an Issue containing only a request for a private contact channel and wait for the maintainer to confirm it before sharing details. This guide does not assert that a private reporting endpoint is enabled. Read [Security](SECURITY.md) for data-handling requirements.

## Set up

Run commands from the repository root. Use Node.js 20.19+, npm, uv, and Python 3.9+ (`python3`). Use the exact Node version in `.nvmrc` when regenerating committed assets; `npm ci` installs the locked build dependencies. A compatible Codex client is needed for native integration checks, not unit tests. The current supported integration target is macOS / Codex. Installation checks, preview checks, and native acceptance have different scopes; see the [installer guide](../docs/INSTALLER.md) for existing evidence and open native/login checks.

```sh
npm ci
uv sync --group dev
npm run build
npm test
```

Run formatting, static checks, generated-file verification, and documentation link checks before a pull request:

```sh
npm run format:check
npm run lint
npm run typecheck
npm run check:generated
npm run check:docs
```

Python development tools are configured in `pyproject.toml` and locked in `uv.lock`. Install them before static checks:

```sh
uv sync --group dev
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

See the CI workflow for the exact checked versions and commands. `npm run check` runs the combined repository checks. Run `npx playwright install chromium` once before `npm run test:e2e` for browser and accessibility checks. Automatic formatting excludes `vendor/dsh` and generated assets so upstream provenance remains valid.

## Source installation and manual recording

Clone the repository for development, then follow the setup steps above:

```sh
git clone https://github.com/xz1220/dsh-trace-plugin.git
cd dsh-trace-plugin
```

For an optional native integration check of your built source checkout, use a separate test environment with its own HOME and CODEX_HOME. Do not replace your personal plugin installation. In that environment, the local marketplace commands are:

```sh
codex plugin marketplace add "$PWD"
codex plugin add codex-dsh-trace@rollout-local
```

The setup helper configures desktop recording. Manual commands below are for source development or a separately configured CLI. Recording must be enabled before starting the Codex process; earlier execution cannot be captured retroactively.

```sh
CODEX_ROLLOUT_TRACE_ROOT="$HOME/.codex/rollout-traces" codex
CODEX_ROLLOUT_TRACE_ROOT="$HOME/.codex/rollout-traces" codex exec --ephemeral "your task"
```

For subsequently launched macOS apps in the current login session:

```sh
mkdir -p -m 700 "$HOME/.codex/rollout-traces"
launchctl setenv CODEX_ROLLOUT_TRACE_ROOT "$HOME/.codex/rollout-traces"
```

Only use that desktop command when intentionally configuring recording: it changes the login-session environment, even when file paths are isolated. It does not close applications. Fully quit and reopen Codex yourself afterwards. The manual environment setting needs to be repeated after logout; remove it with `launchctl unsetenv CODEX_ROLLOUT_TRACE_ROOT` and reopen Codex to disable it. The setup helper's optional login LaunchAgent is a separate path whose startup ordering still needs native evidence.

`scripts/record.py` is also available as a recording helper. From a source checkout, explicitly register another recording root with:

```sh
python3 plugins/codex-dsh-trace/server/main.py --register /absolute/path/to/recordings
```

Registration writes local catalog configuration, not recordings. The npm package is `dsh-trace-extension`, the repository is `dsh-trace-plugin`, the plugin ID is `codex-dsh-trace`, and the panel is **Codex Trace**. See [Architecture](../docs/ARCHITECTURE.md#current-internal-identifiers) for internal identifiers. Client menus and plugin commands can vary by version.

## Repository layout

Start with the [README](../README.md) for installation and use, then this guide for development. Consult the [architecture](../docs/ARCHITECTURE.md) when changing data flow; the table below locates the relevant implementation.

The root keeps user-facing entry documents and files that package managers, editors, and linters discover by convention. Community policies and release configuration live under `.github/`; detailed product and architecture documents live under `docs/`.

| Path                                 | Purpose                                                                       |
| ------------------------------------ | ----------------------------------------------------------------------------- |
| `src/`                               | React integration, MCP Apps host bridge, local styles and preferences         |
| `plugins/codex-dsh-trace/server/`    | Standard-library Python reader and MCP server                                 |
| `plugins/codex-dsh-trace/assets/`    | Generated frontend and plugin branding                                        |
| `packages/dsh-trace-extension/`      | npm CLI, distribution template, and modular Python installer (`installer/`)   |
| `.github/`                           | Contribution and security policies, CI, and release configuration             |
| `vendor/dsh/`                        | Pinned upstream source, licenses, hashes, and reviewed patches                |
| `vendor/licenses/`                   | Additional license texts included in generated dependency notices             |
| `tests/`, `tests/e2e/`, `tests/npm/` | Isolated unit, browser/accessibility, and npm tarball checks                  |
| `scripts/`                           | Build, verification, doc link checks, recording, fixtures, and packaging      |
| `docs/`                              | Product and interface behavior, architecture, installer, reconciliation, etc. |

Regenerable tool caches, coverage, browser results, and retained demo fixtures go under `.cache/`; release archives go under `dist/`. Do not add private recordings, credentials, machine-specific paths, or private working notes to Git or release packages.

## Clean local outputs

Run `npm run clean` to remove caches, test outputs, release archives, and Python bytecode. Add `-- --dependencies` to remove `node_modules/` and `.venv/` too; restore them with `npm ci` and `uv sync --group dev`. Review the cleanup scope before running it. It is for regenerable development outputs, not user recordings or the personal plugin installation.

Browser test artifacts are in `.cache/playwright/`. Coverage and static-check caches are under `.cache/coverage/`, `.cache/mypy/`, and `.cache/ruff/`. CI uploads use those same paths.

## Work with synthetic recordings

Backend tests create recording bundles in temporary directories. They cover schema reading, continuation context, fork history, compaction, indexing, path validation, and paging without access to your Codex data.

For interactive reviews, run the isolated synthetic demo:

```sh
npm run demo
```

The demo uses temporary recording and catalog roots, including the fallback and environment roots, so it does not read your Codex recordings. Open the bootstrap URL printed by the command and stop the server when finished.

To retain a fixture for live-append testing:

```sh
npm run demo -- --directory .cache/demo
```

`scripts/review-fixtures.py --help` describes schema and live-update options. Generate each fixture in an explicitly chosen directory with `--output`; its default is a new temporary directory. The optional `/harness` route exercises the MCP Apps bridge and does not replace native Codex acceptance.

## Change the UI or reader

Preserve original payloads and distinguish recorded facts from inferred presentation. Do not invent hidden text, missing timings, or uncaptured images. Test behavioral changes with a small synthetic regression; avoid tests that only duplicate implementation text. For UI changes, inspect narrow and wide layouts, both themes, keyboard focus, and live updates. Note whether evidence comes from unit tests, local preview, the bridge harness, or a native Codex panel.

## Choose checks and identify evidence

| Change                              | Relevant validation                                                                         |
| ----------------------------------- | ------------------------------------------------------------------------------------------- |
| Documentation                       | Links, commands, versions, supported scope, and sensitive information.                      |
| Reader, index, context, or protocol | Focused synthetic regressions, then `npm test`.                                             |
| UI or host bridge                   | Focused regressions, `npm run test:e2e`, and the relevant preview, harness, or native flow. |
| npm setup or packaging              | Build, `npm run test:npm`, tarball contents, and isolated lifecycle checks.                 |
| Vendored DSH or generated resources | Upstream integrity, regenerated assets, interactions, and third-party notices.              |

For code PRs, run applicable targeted checks and `npm run check`. Coverage and browser/npm checks are separate commands; the [CI workflow](workflows/ci.yml) defines the complete automated set. Avoid unrelated whole-repository formatting.

Unit/protocol tests establish synthetic input and interface behavior. Local preview establishes browser behavior with its fixture. The MCP Apps harness simulates a host bridge. Native Codex evidence must identify OS/client versions and the actual steps. The first three do not establish native installation, reload, or recording after login. Automated accessibility checks also need manual keyboard and native-host review.

## Update DSH

Read [vendor/dsh/PATCHES.md](../vendor/dsh/PATCHES.md) first. The update script overwrites imported source, including local patches.

1. Prepare an audited checkout of the pinned upstream project.
2. Review/update the repository and commit pin in `vendor/dsh/upstream.json`, then run `node scripts/vendor-dsh.mjs /absolute/path/to/deepseek-harness` against a clean checkout of that commit. The importer rejects a different HEAD, tracked modifications, or untracked files.
3. Reapply and review the required adapters. Update `patches.json` hashes and `PATCHES.md`; do not allow unexplained changes.
4. Run `node scripts/verify-dsh.mjs`, rebuild, run tests, and inspect the changed interactions.
5. Review the generated third-party notices and commit source changes together with generated artifacts.

Do not format vendored files automatically or disable integrity verification to make an update pass.

## Package and release

The version in `package.json` is authoritative. A build generates the plugin manifest version, frontend version module, and Python version module. Change the source version and rebuild rather than editing those generated copies.

The ordinary user installation path is the self-contained npm package. Build and inspect it with:

```sh
npm run build
npm run package:npm
npm run test:npm
```

The tarball must include the CLI, installer modules, verified built plugin, manifest, and licenses without tests, user configuration, recordings, or the full source repository. Check stable-copy behavior, repeat setup, doctor, uninstall, and preservation of unrelated data in isolated HOME/CODEX_HOME directories. Test interruption/recovery or upgrade claims separately from a fresh install. Review the exact tarball and obtain publication authorization before publishing; packaging or PR approval alone does not authorize publication.

The first npm release is `0.2.19`, published on 2026-11-17. Earlier development versions do not create a release or migration contract. Define and verify later upgrade behavior from that baseline before release; repeat setup is not cross-version upgrade evidence. Existing validation and remaining native/login checks are documented in the [installer guide](../docs/INSTALLER.md).

After `npm run build`, use `npm run package` to create an installable ZIP and checksums under `dist/`. Packaging checks generated assets and fails if they are stale; it does not silently repair them. Keep the generated frontend, plugin metadata, and dependency notices consistent with the source. The generated-file check should leave the working tree clean on a committed build.

The **Prepare release PR** workflow uses [Release Please](https://github.com/googleapis/release-please-action) to propose the next package version and generate changelog entries from Conventional Commits. It is opt-in: after configuring the permissions below, set the repository Actions variable `ENABLE_RELEASE_PLEASE` to `true` to run it automatically on pushes to `main`. Maintainers can also start the workflow manually on `main` to try it before enabling automatic runs. The same workflow rebuilds and commits the derived assets to that release PR, so reviewers can inspect the exact distributable before merging. [`.release-please-manifest.json`](.release-please-manifest.json) records release history alongside the [release configuration](release-please-config.json) in `.github/`; it is not another runtime version source. The workflow deliberately does not create tags or publish releases.

To run PR CI automatically on these bot-created changes, configure the repository secret `RELEASE_PLEASE_TOKEN` with a repository-scoped token that can write contents, pull requests, and issues. GitHub may also require **Allow GitHub Actions to create and approve pull requests** in repository settings. Without that secret, the workflow uses `GITHUB_TOKEN` and validates the generated build itself; GitHub does not trigger the separate PR CI from that token. A maintainer must manually run **CI** on the release PR branch before merging. See the [official token behavior](https://github.com/googleapis/release-please-action#other-actions-on-release-please-prs).

After reviewing and merging the release PR, a maintainer pushes a `v<version>` tag for that merged commit. **Release plugin** verifies that the tag matches `package.json`, runs the full quality/check and npm tarball verification suites with the canonical toolchain, packages the ZIP, and publishes it with checksums. Its release description comes from the reviewed changelog entry for that version; a missing entry fails the release. An optional approval-gated `publish-npm` job supports OIDC trusted publishing with `--provenance` when `ENABLE_NPM_PUBLISH` is enabled (or triggered via `workflow_dispatch`) and the `npm-release` environment is configured.

Release Please's [extra-file updaters](https://github.com/googleapis/release-please/blob/main/docs/customizing.md#updating-arbitrary-files) can replace version fields, but cannot regenerate the compiled HTML. This project therefore derives all runtime copies through `npm run build` rather than configuring independent version substitutions.

Document user-visible behavior in [CHANGELOG.md](../CHANGELOG.md). Keep installation status, personal paths, and one-off validation logs out of public documentation. Native installation and reload behavior must be verified separately from packaging.

## Submit a pull request

Use focused commits and Conventional Commit titles, such as `fix: preserve resumed request order` or `docs: clarify desktop recording`. Explain the trigger, resulting behavior, and relevant verification. Mention remaining compatibility limits. Large formatting-only changes should be separate from behavior changes and listed in `.git-blame-ignore-revs` when that file exists.

## Repository protection

After CI has run successfully, maintainers can require the quality and browser checks in a branch rule for `main`. Keep force pushes and branch deletion disabled. Enable private vulnerability reporting where available. CodeQL runs automatically for public repositories; private repositories with GitHub Code Security can opt in with `ENABLE_CODEQL=true`. These hosting settings are separate from the files in this repository. Workflow definitions and policy links do not establish that a hosting feature is enabled or that a particular run passed.
