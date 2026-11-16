# Pinned sources

These references explain the original implementation baseline. They do not imply that later upstream releases keep the same APIs or recording formats.

## Codex

Original integration used Codex CLI 0.163.0 and source commit `83086188ae0614bd882818ff1aa23f3194962012`.

- [Official rollout-trace source](https://github.com/openai/codex/tree/83086188ae0614bd882818ff1aa23f3194962012/codex-rs/rollout-trace)
- [Inference recording implementation](https://github.com/openai/codex/blob/83086188ae0614bd882818ff1aa23f3194962012/codex-rs/rollout-trace/src/inference.rs)

The production plugin reads official local recordings. It does not depend on third-party session viewers.

## DeepSeek Harness

Runtime source is pinned to `deepseek-ai/deepseek-harness` commit `e8f7b93a344964de3dca1ace9e72b6e4d6de87cb`.

- [Trajectory components](https://github.com/deepseek-ai/deepseek-harness/tree/e8f7b93a344964de3dca1ace9e72b6e4d6de87cb/packages/client/ui-trajectory)
- [Theme source](https://github.com/deepseek-ai/deepseek-harness/tree/e8f7b93a344964de3dca1ace9e72b6e4d6de87cb/packages/client/ui-theme)
- [Imported file manifest](../vendor/dsh/upstream.json), [approved hashes](../vendor/dsh/patches.json), and [adaptation rationale](../vendor/dsh/PATCHES.md)
- [Upstream license](../vendor/dsh/LICENSE)

Historical design-study references are separately pinned in `design/dsh-sources.json`. Their downloaded cache is ignored; generated studies contain synthetic demonstrations and source excerpts.

## Evidence policy

Public unit tests and synthetic fixture generators are the reproducible evidence for regression checks. A historical manual validation report is an observation, not an executable test. Local browser preview, bridge-handshake testing, and native Codex acceptance are distinct scopes and should be identified accurately in changes and release notes.
