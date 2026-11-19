# Repository Guidelines

## Project Structure & Module Organization

- `src/`: React UI, host bridge, styles, and localization.
- `plugins/codex-dsh-trace/server/`: standard-library Python reader/MCP server; sibling `assets/` contains generated frontend and branding.
- `packages/dsh-trace-extension/`: npm CLI, distribution template, and Python installer modules (`installer/`); `scripts/`: build, packaging, doc checks, and fixture tools.
- `tests/`: unit suites; `tests/e2e/`: browser checks; `tests/npm/`: tarball checks.
- `vendor/dsh/`: pinned upstream components; `docs/` and `.github/`: architecture and contribution policies.

## Build, Test, and Development Commands

Use Node from `.nvmrc`, Python 3.9+, and uv. Run from the repository root:

- `npm ci` and `uv sync --group dev`: install development dependencies.
- `npm run build`: regenerate plugin assets.
- `npm run demo`: start an isolated synthetic preview.
- `npm run check`: run lint, formatting, mypy, unit tests, generated-file verification, and doc-link verification.
- `npm run package` / `npm run package:npm`: create ZIP/npm distributions under `dist/`.

## Coding Style & Naming Conventions

Use two-space indentation for JS/JSX and four for Python; target 100 columns. Prettier uses single quotes and trailing commas; ESLint checks React hooks; Ruff formats/lints Python. Use PascalCase components, camelCase JS functions, and snake_case Python names. Run `npm run format`; never autoformat `vendor/dsh/`.

## Testing Guidelines

`npm test` runs Python unittest (`test_*.py`) and Node's test runner (`test_*.mjs`). Run `npm run test:e2e` (`*.spec.mjs`) after `npx playwright install chromium`; run `npm run test:npm` for packaging changes. `npm run test:coverage` requires Python coverage of 75%; selected JS modules require 80% lines/functions and 65% branches. Add synthetic regressions for behavioral changes.

## Commit & Pull Request Guidelines

Follow Conventional Commits, e.g. `fix: preserve resumed request order`. Use `.github/PULL_REQUEST_TEMPLATE.md`: describe the problem, resulting behavior, checks, and compatibility limits. Include synthetic screenshots when useful; identify preview, harness, or native evidence. Rebuild and commit affected generated files; document vendor patches in `vendor/dsh/PATCHES.md`.

## Development Boundaries & Data Safety

The GitHub source became public on 2026-11-16. The first npm release, [`dsh-trace-extension@0.2.19`](https://www.npmjs.com/package/dsh-trace-extension/v/0.2.19), was published on 2026-11-17. Prioritize self-contained `npx dsh-trace-extension setup` without GitHub authentication, cloning, or local builds. Only macOS/Codex integration is supported; Antigravity remains a future candidate.

Skip migrations for historical development installations. Development version numbers, internal installations, and commits do not create a release contract. Use `0.2.19` as the baseline for future compatibility decisions; define and verify upgrade behavior before the next release rather than claiming cross-version upgrades are supported.

Isolate tests using temporary `HOME`/`CODEX_HOME`; preserve existing configuration, installations, recordings, and unrelated files. Never commit private traces, credentials, or bootstrap URLs. Prepare and verify publication contents before requesting explicit authorization to publish npm packages or expose private repositories.
