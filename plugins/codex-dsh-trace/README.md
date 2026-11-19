# Codex Trace

A local Codex MCP App for official `rollout-trace` recordings. Plugin ID: `codex-dsh-trace@rollout-local`.

## Install and update

Recommended installation uses the self-contained npm setup helper (no GitHub login, source checkout, or local build required):

```sh
npx dsh-trace-extension setup
```

To check status or uninstall a helper-managed installation:

```sh
npx dsh-trace-extension doctor
npx dsh-trace-extension uninstall
```

Fully quit and reopen Codex after installing or updating so it reloads both the Python backend and the bundled frontend. Run a new task, then choose **Codex Trace** in the conversation's right-panel tools menu.

The built plugin requires Python **3.9+** as `python3` (launched with `-B`) and a compatible Codex client. The runtime reader needs no Python packages or Node.js runtime. macOS / Codex is the currently supported target; Linux and Windows native integrations remain unverified. Codex CLI 0.163.0 is the historical integration baseline, not a minimum-version guarantee.

### Alternative: source or Git marketplace

For source development or isolated manual testing (do not mix with an existing npm-managed `rollout-local` registration in the same Codex profile):

```sh
codex plugin marketplace add xz1220/dsh-trace-plugin
codex plugin add codex-dsh-trace@rollout-local
```

To update a Git marketplace checkout, run `codex plugin marketplace upgrade rollout-local`, then add the plugin again and restart Codex.

See the [project README](https://github.com/xz1220/dsh-trace-plugin#readme) and [installer guide](https://github.com/xz1220/dsh-trace-plugin/blob/main/docs/INSTALLER.md) for full installation, troubleshooting, and development instructions.

## Enable recording

Enable tracing before starting Codex:

```sh
CODEX_ROLLOUT_TRACE_ROOT="$HOME/.codex/rollout-traces" codex
```

For subsequently launched macOS desktop apps in the current login session:

```sh
mkdir -p -m 700 "$HOME/.codex/rollout-traces"
launchctl setenv CODEX_ROLLOUT_TRACE_ROOT "$HOME/.codex/rollout-traces"
```

Fully quit and reopen Codex afterwards. Existing history cannot be captured retroactively. Register another recording directory from this plugin directory with `python3 server/main.py --register /absolute/path/to/recordings`.

## Inspect recordings

The panel follows the current chat, host theme and language, and new events automatically. It shows DSH timeline and ledger views, search, requests and nested tools, recorded images, and compaction. Complete context and original request/response JSON remain separate. Recordings join only for the same exact root thread, preserving resumed history and recorded provenance.

Supported schemas are **1 and 2**. Event logs are limited to **256 MiB**, including a chat aggregate; each payload is limited to **64 MiB**. Exceeded limits and unavailable evidence are reported explicitly. Opaque content, uncaptured images, and unrecorded timing cannot be reconstructed.

## Local data and compatibility

Recordings remain read-only. Discovery uses `$CODEX_HOME/rollout-traces` (default `~/.codex/rollout-traces`), `CODEX_ROLLOUT_TRACE_ROOT`, and registered directories. Registration writes only `$CODEX_HOME/rollout-viewer/config.json`. The `rollout-viewer` MCP/resource namespace, configuration, preferences, and legacy resource alias remain compatible with earlier installations.

The reader has no upload, telemetry, or model integration. Detailed tools are app-only visibility hints enforced by the host. Recordings can contain credentials and private code; review content before copying, exporting, or sharing it. The optional `python3 server/main.py --preview` binds to loopback and prints a secret bootstrap URL; keep it private and stop the server when finished. Its bridge harness does not establish native Codex compatibility. See [security and privacy](https://github.com/xz1220/dsh-trace-plugin/blob/main/.github/SECURITY.md).

## Attribution

Independently maintained; **not an official OpenAI or DeepSeek product**. DSH components are MIT licensed, © 2026 DeepSeek. See the included `LICENSE` and `THIRD_PARTY_NOTICES.txt`.
