# Contributing to Codex Trace

Bug reports, documentation improvements, and focused patches are welcome. Read the [code of conduct](CODE_OF_CONDUCT.md) and use synthetic data when describing a problem. Report security issues through [SECURITY.md](SECURITY.md).

## Set up

Use Node.js 20.19+, npm, and Python 3.9+ (`python3`). Use the exact Node version in `.nvmrc` when regenerating committed assets; `npm ci` installs the locked build dependencies. A compatible Codex client is needed only for native integration checks, not unit tests. macOS arm64 is the native integration baseline; other platforms need evidence before being described as verified.

```sh
npm ci
npm run build
npm test
```

Run formatting, static checks, and the generated-file check before a pull request:

```sh
npm run format:check
npm run lint
npm run typecheck
npm run check:generated
```

Python development tools are configured in `pyproject.toml` and locked in `uv.lock`. Install them before static checks:

```sh
uv sync --group dev
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

See the CI workflow for the exact checked versions and commands. `npm run check` runs the combined repository checks. Run `npx playwright install chromium` once before `npm run test:e2e` for browser and accessibility checks. Automatic formatting excludes `vendor/dsh`, generated assets, and historical prototypes so upstream provenance remains valid.

## Repository layout

| Path                              | Purpose                                                               |
| --------------------------------- | --------------------------------------------------------------------- |
| `src/`                            | React integration, MCP Apps host bridge, local styles and preferences |
| `plugins/codex-dsh-trace/server/` | Standard-library Python reader and MCP server                         |
| `plugins/codex-dsh-trace/assets/` | Generated frontend and plugin branding                                |
| `vendor/dsh/`                     | Pinned upstream source, licenses, hashes, and reviewed patches        |
| `tests/`                          | Isolated Python and Node regression tests                             |
| `scripts/`                        | Build, verification, recording, fixtures, and packaging               |
| `docs/`                           | Product, architecture, design, and source notes                       |
| `design/`                         | Historical synthetic prototypes, kept separate from the runtime       |

`local-context/`, screenshots used for private review, caches, and `dist/` are local artifacts. Do not add captured private traces to Git.

## Work with synthetic recordings

Backend tests create recording bundles in temporary directories. They cover schema reading, continuation context, fork history, compaction, indexing, path validation, and paging without access to your Codex data.

For interactive reviews, run the isolated synthetic demo:

```sh
npm run demo
```

The demo uses temporary recording and catalog roots, including the fallback and environment roots, so it does not read your Codex recordings. Open the bootstrap URL printed by the command and stop the server when finished.

To retain a fixture for live-append testing:

```sh
npm run demo -- --directory local-context/demo
```

`scripts/review-fixtures.py --help` describes schema and live-update options. Generate each fixture in an explicitly chosen directory with `--output`; its default is a new temporary directory. The optional `/harness` route exercises the MCP Apps bridge and does not replace native Codex acceptance.

## Change the UI or reader

Preserve original payloads and distinguish recorded facts from inferred presentation. Do not invent hidden text, missing timings, or uncaptured images. Test behavioral changes with a small synthetic regression; avoid tests that only duplicate implementation text. For UI changes, inspect narrow and wide layouts, both themes, keyboard focus, and live updates. Note whether evidence comes from unit tests, local preview, the bridge harness, or a native Codex panel.

## Update DSH

Read [vendor/dsh/PATCHES.md](vendor/dsh/PATCHES.md) first. The update script overwrites imported source, including local patches.

1. Prepare an audited checkout of the pinned upstream project.
2. Review/update the commit in `scripts/vendor-dsh.mjs`, then run `node scripts/vendor-dsh.mjs /absolute/path/to/deepseek-harness`.
3. Reapply and review the required adapters. Update `patches.json` hashes and `PATCHES.md`; do not allow unexplained changes.
4. Run `node scripts/verify-dsh.mjs`, rebuild, run tests, and inspect the changed interactions.
5. Review the generated third-party notices and commit source changes together with generated artifacts.

Do not format vendored files automatically or disable integrity verification to make an update pass.

## Package and release

The version in `package.json` is authoritative. A build generates the plugin manifest version, frontend version module, and Python version module. Change the source version and rebuild rather than editing those generated copies.

After `npm run build`, use `npm run package` to create an installable ZIP and checksums under `dist/`. Packaging checks generated assets and fails if they are stale; it does not silently repair them. Keep the generated frontend, plugin metadata, and dependency notices consistent with the source. The generated-file check should leave the working tree clean on a committed build.

The **Prepare release PR** workflow uses [Release Please](https://github.com/googleapis/release-please-action) to propose the next package version and generate changelog entries from Conventional Commits. It is opt-in: after configuring the permissions below, set the repository Actions variable `ENABLE_RELEASE_PLEASE` to `true` to run it automatically on pushes to `main`. Maintainers can also start the workflow manually on `main` to try it before enabling automatic runs. The same workflow rebuilds and commits the derived assets to that release PR, so reviewers can inspect the exact distributable before merging. `.release-please-manifest.json` records release history; it is not another runtime version source. The workflow deliberately does not create tags or publish releases.

To run PR CI automatically on these bot-created changes, configure the repository secret `RELEASE_PLEASE_TOKEN` with a repository-scoped token that can write contents, pull requests, and issues. GitHub may also require **Allow GitHub Actions to create and approve pull requests** in repository settings. Without that secret, the workflow uses `GITHUB_TOKEN` and validates the generated build itself; GitHub does not trigger the separate PR CI from that token. A maintainer must manually run **CI** on the release PR branch before merging. See the [official token behavior](https://github.com/googleapis/release-please-action#other-actions-on-release-please-prs).

After reviewing and merging the release PR, a maintainer pushes a `v<version>` tag for that merged commit. **Release plugin** verifies that the tag matches `package.json`, checks tests and committed artifacts with the canonical toolchain, packages the ZIP, and publishes it with checksums. Its release description comes from the reviewed changelog entry for that version; a missing entry fails the release.

Release Please's [extra-file updaters](https://github.com/googleapis/release-please/blob/main/docs/customizing.md#updating-arbitrary-files) can replace version fields, but cannot regenerate the compiled HTML. This project therefore derives all runtime copies through `npm run build` rather than configuring independent version substitutions.

Document user-visible behavior in [CHANGELOG.md](CHANGELOG.md). Keep installation status, personal paths, and one-off validation logs out of public documentation. Native installation and reload behavior must be verified separately from packaging.

## Submit a pull request

Use focused commits and Conventional Commit titles, such as `fix: preserve resumed request order` or `docs: clarify desktop recording`. Explain the trigger, resulting behavior, and relevant verification. Mention remaining compatibility limits. Large formatting-only changes should be separate from behavior changes and listed in `.git-blame-ignore-revs` when that file exists.

## Repository protection

After CI has run successfully, maintainers can require the quality and browser checks in a branch rule for `main`. Keep force pushes and branch deletion disabled. Enable private vulnerability reporting where available. CodeQL runs automatically for public repositories; private repositories with GitHub Code Security can opt in with `ENABLE_CODEQL=true`. These hosting settings are separate from the files in this repository.
