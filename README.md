# Codex Trace

Read recorded Codex requests, nested tool calls, compaction, and execution timing alongside your conversation.

[简体中文](README.zh-CN.md) · [Contributing](.github/CONTRIBUTING.md) · [Architecture](docs/ARCHITECTURE.md) · [Security](.github/SECURITY.md)

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

- macOS and a Codex client that supports local plugins, MCP Apps, and official `rollout-trace` recording. Compatibility depends on the client and recording schema.
- Python **3.9+** available as `python3`. No Python packages are required.
- Node.js **20.19+** and npm/npx for the setup helper or source development. The installed Python backend does not need Node.js at runtime.

macOS arm64 has been checked locally. The original integration used Codex CLI 0.163.0; that is a historical test baseline, not a minimum-version guarantee. CI checks the reader and build on Ubuntu; Linux and Windows native Codex integrations remain unverified. The reader supports recording schemas **1 and 2**.

## Install

```sh
npx dsh-trace-extension setup
```

The package includes the built plugin and setup tools. Setup displays its plan, installs a stable local copy, and configures recording after confirmation. It does not require a GitHub account, a source checkout, or a frontend build.

Fully quit and reopen Codex after setup, run a new task, then open **Codex Trace** from the conversation's right-panel tools menu.

See the [installer guide](docs/INSTALLER.md) for configuration options and the first release, [`0.2.19`](https://www.npmjs.com/package/dsh-trace-extension/v/0.2.19).

## Check and uninstall

```sh
npx dsh-trace-extension doctor
npx dsh-trace-extension uninstall
```

Uninstall preserves recordings and unrelated configuration. Repeat setup reuses its own unchanged installation. Future cross-version upgrades will be documented and verified before release.

## Build from source

For development or a local marketplace installation:

```sh
git clone https://github.com/xz1220/dsh-trace-plugin.git
cd dsh-trace-plugin
npm ci
npm run build
codex plugin marketplace add "$PWD"
codex plugin add codex-dsh-trace@rollout-local
```

Open **Codex Trace** from the conversation's right-panel tools menu. Reopen the panel or restart Codex after installation if the entry does not appear. Client menus and plugin commands can differ between Codex versions.

The npm package is `dsh-trace-extension`; the repository is `dsh-trace-plugin`, the plugin ID is `codex-dsh-trace`, and the native entry is **Codex Trace**. See [Architecture](docs/ARCHITECTURE.md#current-internal-identifiers) for internal namespaces.

## Manual recording (optional)

The setup helper configures desktop recording; these manual commands are for source development or a separately configured CLI. Recording must be enabled **before Codex starts**. Existing conversations cannot be captured retroactively.

For a new CLI process:

```sh
CODEX_ROLLOUT_TRACE_ROOT="$HOME/.codex/rollout-traces" codex
```

Or record one scripted task:

```sh
CODEX_ROLLOUT_TRACE_ROOT="$HOME/.codex/rollout-traces" codex exec --ephemeral "your task"
```

On macOS, configure subsequently launched desktop apps for the current login session:

```sh
mkdir -p -m 700 "$HOME/.codex/rollout-traces"
launchctl setenv CODEX_ROLLOUT_TRACE_ROOT "$HOME/.codex/rollout-traces"
```

Fully quit and reopen Codex afterwards. Repeat the command after logging out. To disable desktop recording, run `launchctl unsetenv CODEX_ROLLOUT_TRACE_ROOT` and restart Codex. These commands do not close the application. Source checkouts also include `scripts/record.py` as a recording helper.

From a source checkout, register another recording directory:

```sh
python3 plugins/codex-dsh-trace/server/main.py --register /absolute/path/to/recordings
```

## Privacy and data

The plugin reads official local trace bundles from the default recording root, `CODEX_ROLLOUT_TRACE_ROOT`, and directories you register. It does not substitute ordinary session logs. Registration writes a small configuration file under `$CODEX_HOME/rollout-viewer/` (default `~/.codex/rollout-viewer/`); it does not modify recordings.

The reader has no upload, analytics, or remote-service integration. Recording data is delivered to the local Codex app for display. The optional preview serves the same data on authenticated loopback HTTP. Follow external links and use copy or export actions with care: recordings can include credentials, private code, prompts, and images. Read [Security](.github/SECURITY.md) before sharing a trace or screenshot.

## Troubleshooting

**The viewer is empty.** Confirm recording was enabled before the Codex process started and that its root matches the current chat. Opening the viewer does not start recording. An empty resumed recording waits for new data automatically.

**The plugin still looks like an older version.** Installed files and an open Codex connection can differ. Fully quit and reopen the client after updating. Installing a package alone does not prove that a running panel has reloaded.

**A recording is unsupported or too large.** Schemas 1 and 2 are supported. The current limits are 256 MiB of event logs and 64 MiB per payload. Limits produce an explicit error. A current-chat aggregate over the limit can still be inspected as individual captures through the API.

**Some historical text or timing is missing.** The viewer shows what was recorded. Opaque compaction items, uncaptured images, missing continuation prefixes, and unrecorded generation timings cannot be reconstructed reliably.

## Development

```sh
npm ci
npm run build
npm test
```

Run `npm run demo` for an isolated synthetic recording without access to personal Codex data.

Start with this README for installation and use, then follow the [contribution guide](.github/CONTRIBUTING.md) for setup, checks, and the repository map. Read the [architecture](docs/ARCHITECTURE.md) when changing the reader or UI; [product behavior](docs/PRODUCT.md) and the [roadmap](docs/ROADMAP.md) provide the detailed constraints and planned work.

## Attribution and license

Independently maintained; **not an official OpenAI or DeepSeek product**. The interface includes MIT-licensed components from [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness), pinned and documented in [vendor/dsh/PATCHES.md](vendor/dsh/PATCHES.md). DSH refers to that upstream project.

This project's code is MIT licensed; see [LICENSE](LICENSE). Built plugin packages include `LICENSE` and `THIRD_PARTY_NOTICES.txt` with the bundled dependencies' notices.
