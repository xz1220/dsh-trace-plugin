# Codex Trace

Read recorded Codex requests, nested tool calls, compaction, and execution timing alongside your conversation.

[简体中文](README.zh-CN.md) · [Contributing](CONTRIBUTING.md) · [Architecture](docs/ARCHITECTURE.md) · [Security](SECURITY.md)

![Codex Trace displaying a synthetic execution recording](docs/images/trace-viewer.png)

_The screenshot uses synthetic data in the local preview. It does not contain a private conversation or demonstrate a native Codex installation._

## Features

- Open the current chat's recording automatically and follow new events.
- Explore the DSH timeline and execution ledger with folding, search, and a resizable inspector.
- Compare reconstructed context with the incremental request and original response JSON.
- Follow nested calls, recorded subtool declarations, and tool results, including recorded images.
- Keep earlier requests visible across resumed recordings, fork history, and compaction.
- Read large recordings through incremental indexing, virtualized rows, and on-demand details.
- Follow the host's theme and language. Upstream controls support eight locales; Codex-specific text currently falls back to Chinese or English.

## Requirements

- A Codex client that supports local plugins, MCP Apps, and official `rollout-trace` recording. Compatibility depends on the client and recording schema.
- Python **3.9+** available as `python3`. No Python packages are required.
- Node.js **20.19+** and npm to build or develop from source. An already-built plugin does not need Node.js at runtime.

macOS arm64 has been checked locally. The original integration used Codex CLI 0.163.0; that is a historical test baseline, not a minimum-version guarantee. CI checks the reader and build on Ubuntu; Linux and Windows native Codex integrations remain unverified. The reader supports recording schemas **1 and 2**.

## Install from source

```sh
git clone https://github.com/xz1220/codex-dsh-trace.git
cd codex-dsh-trace
npm ci
npm run build
codex plugin marketplace add "$PWD"
codex plugin add codex-dsh-trace@rollout-local
```

Open **Codex Trace** from the conversation's right-panel tools menu. Reopen the panel or restart Codex after installation if the entry does not appear. Client menus and plugin commands can differ between Codex versions.

The repository is `codex-dsh-trace`; the displayed product name is **Codex Trace**. Existing `rollout-viewer` MCP identifiers and configuration remain supported for compatibility. See [Architecture](docs/ARCHITECTURE.md#compatibility-identifiers).

## Enable recording

Recording must be enabled **before Codex starts**. Existing conversations cannot be captured retroactively.

For a new CLI process:

```sh
CODEX_ROLLOUT_TRACE_ROOT="$HOME/.codex/rollout-traces" codex
```

Or record one scripted task with the helper:

```sh
python3 scripts/record.py -- exec --ephemeral "your task"
```

On macOS, configure subsequently launched desktop apps for the current login session:

```sh
python3 scripts/record.py --desktop-env
```

Fully quit and reopen Codex afterwards. Repeat the command after logging out. To disable desktop recording, run `launchctl unsetenv CODEX_ROLLOUT_TRACE_ROOT` and restart Codex. The helper does not close the application itself.

To register another recording directory:

```sh
python3 plugins/codex-dsh-trace/server/main.py --register /absolute/path/to/recordings
```

## Privacy and data

The plugin reads official local trace bundles from the default recording root, `CODEX_ROLLOUT_TRACE_ROOT`, and directories you register. It does not substitute ordinary session logs. Registration writes a small configuration file under `$CODEX_HOME/rollout-viewer/` (default `~/.codex/rollout-viewer/`); it does not modify recordings.

The reader has no upload, analytics, or remote-service integration. Recording data is delivered to the local Codex app for display. The optional preview serves the same data on authenticated loopback HTTP. Follow external links and use copy or export actions with care: recordings can include credentials, private code, prompts, and images. Read [Security](SECURITY.md) before sharing a trace or screenshot.

## Troubleshooting

**The viewer is empty.** Confirm recording was enabled before the Codex process started and that its root matches the current chat. Opening the viewer does not start recording. An empty resumed recording waits for new data automatically.

**The plugin still looks like an older version.** Installed files and an open Codex connection can differ. Reopen the panel or restart the client. Installing a package alone does not prove that a running panel has reloaded.

**A recording is unsupported or too large.** Schemas 1 and 2 are supported. The current limits are 256 MiB of event logs and 64 MiB per payload. Limits produce an explicit error. A current-chat aggregate over the limit can still be inspected as individual captures through the API.

**Some historical text or timing is missing.** The viewer shows what was recorded. Opaque compaction items, uncaptured images, missing continuation prefixes, and unrecorded generation timings cannot be reconstructed reliably.

## Development

```sh
npm ci
npm run build
npm test
```

Run `npm run demo` for an isolated synthetic recording without access to personal Codex data.

See [CONTRIBUTING.md](CONTRIBUTING.md) for formatting, CI checks, synthetic fixtures, the browser preview, packaging, and the DSH update workflow. Product behavior and planned work are documented in [docs/PRODUCT.md](docs/PRODUCT.md) and [docs/ROADMAP.md](docs/ROADMAP.md).

## Attribution and license

Independently maintained; **not an official OpenAI or DeepSeek product**. The interface includes MIT-licensed components from [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness), pinned and documented in [vendor/dsh/PATCHES.md](vendor/dsh/PATCHES.md). DSH refers to that upstream project.

This project's code is MIT licensed; see [LICENSE](LICENSE). Built plugin packages include `LICENSE` and `THIRD_PARTY_NOTICES.txt` with the bundled dependencies' notices. Historical synthetic design studies remain in [design/](design/README.md).
