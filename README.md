# Codex Trace

Bring the DSH trace-viewing experience into Codex. Inspect agent actions and their recorded evidence to understand and use agents better.

View recorded model requests, tool calls, context changes, and execution timing alongside your conversation. The current integration is **macOS / Codex**.

[简体中文](README.zh-CN.md) · [Installer guide](docs/INSTALLER.md) · [Contributing](.github/CONTRIBUTING.md) · [Security](.github/SECURITY.md)

![Codex Trace displaying a synthetic execution recording](docs/images/trace-viewer.png)

_The screenshot uses synthetic data in the local preview. It contains no private conversation and does not demonstrate native Codex acceptance._

## What you can inspect

- **How execution unfolds:** use the DSH timeline and ledger to inspect requests, nested tool calls, results, and recorded images, with search, folding, and a detail inspector.
- **What the model receives:** compare reconstructed complete context, the incremental request actually sent, and original response JSON.
- **Where time goes:** inspect available request and tool timing to locate steps that need closer examination.
- **How history continues:** keep existing history and its sources visible across resumed tasks, forks, and compaction, while following new events for the current chat.

The viewer uses official `rollout-trace` recordings. Uncaptured images, opaque compacted text, and missing timing remain unavailable. It cannot recover earlier unrecorded execution or guarantee an explanation of every model decision.

## Get started

You need macOS and a compatible Codex client with local plugins, MCP Apps, and official recording support. Setup also needs a `codex` CLI on PATH with plugin commands, `python3` (Python 3.9+), and Node.js 20.19+ with npm/npx. The reader supports recording schemas 1 and 2; other systems and hosts are not claimed as supported.

**Validation scope:** the first npm release, `0.2.19`, has installation-lifecycle evidence from an isolated environment. Native-sidebar acceptance and recording startup order after login remain unverified. Compatibility depends on the client version and recording format; installation success alone does not establish native readiness.

```sh
npx dsh-trace-extension setup
```

1. Review the files and settings in the setup plan, then confirm installation.
2. Fully quit and reopen Codex so the new process receives the recording settings.
3. Run a new task, then open **Codex Trace** from the conversation's right-panel tools menu.

The package includes the built plugin: no GitHub login, source checkout, or local build is required. Setup installs a stable local copy and configures recording; clearing the npm cache does not remove that copy. Recording must be enabled before the Codex process starts. Opening the viewer does not start recording.

See the [installer guide](docs/INSTALLER.md) for options and validation limits. To review the plan first:

```sh
npx dsh-trace-extension setup --dry-run
```

## Check and uninstall

```sh
npx dsh-trace-extension doctor
npx dsh-trace-extension uninstall
```

doctor checks settings and files. Repeat setup reuses its own unchanged installation; uninstall preserves recordings and unrelated configuration. Cross-version upgrade behavior will be documented and verified before a future release, using `0.2.19` as the compatibility baseline.

## Troubleshooting

**The panel is empty.** Check that recording was enabled before Codex started and that the recording belongs to the current chat. Earlier execution cannot be captured retroactively. An empty resumed recording continues waiting for new events.

**Text, images, or timing are missing.** The viewer displays available evidence without inventing uncaptured content. Unsupported formats and exceeded limits produce explicit errors; event logs are limited to 256 MiB and each payload to 64 MiB.

**The panel still looks like an older version.** Installed files and an open panel can differ. Fully quit and reopen the client before checking again. See the [installer guide](docs/INSTALLER.md).

## Data handling

The plugin reads official recordings locally without modifying them; explicit directory registration writes local configuration. The reader has no active recording upload, analytics, or remote-service integration. Native mode passes content to the local Codex host for display; optional preview uses authenticated loopback HTTP.

Recordings can contain prompts, credentials, private code, tool output, and images. Local processing does not eliminate every risk or guarantee how the host handles received data. Read [Security](.github/SECURITY.md) before copying, exporting, sharing screenshots, or following external links.

## Contribute

Use [GitHub Issues and PRs](.github/CONTRIBUTING.md#issues-and-proposals) for feedback and contributions. Discuss larger changes first. The maintainer prioritizes work using evidence and scope, without fixed response or repair deadlines. See [Contributing](.github/CONTRIBUTING.md) for development setup, repository paths, and checks, and [development usage](.github/CONTRIBUTING.md#source-installation-and-manual-recording) for source installation and manual recording. Run `npm run demo` from a source checkout for isolated synthetic recordings without reading personal Codex data. Use synthetic examples in reports.

See [Architecture](docs/ARCHITECTURE.md), [Product behavior](docs/PRODUCT.md), and the [Roadmap](docs/ROADMAP.md) for implementation and behavior boundaries.

Independently maintained; **not an official OpenAI or DeepSeek product**. The interface includes pinned, MIT-licensed components from [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) (DSH); see [vendor/dsh/PATCHES.md](vendor/dsh/PATCHES.md) for adaptations. This project is [MIT licensed](LICENSE), and distributions include third-party notices.
