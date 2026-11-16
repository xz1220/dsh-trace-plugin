# Codex Trace

A local Codex MCP App for official `rollout-trace` recordings. Plugin ID: `codex-dsh-trace@rollout-local`.

## Install and update

```sh
codex plugin marketplace add xz1220/dsh-trace-plugin
codex plugin add codex-dsh-trace@rollout-local
```

The repository ships the built frontend; Node.js and a source build are not required. A private repository requires Git access.

To update:

```sh
codex plugin marketplace upgrade rollout-local
codex plugin add codex-dsh-trace@rollout-local
```

Fully quit and reopen Codex after updating to reload the backend and frontend.

## Open and record

See the [installation instructions](https://github.com/xz1220/dsh-trace-plugin#install). Choose **Codex Trace** in the conversation's right-panel tools menu. The panel follows the current chat and new recordings automatically. It has no recording-management settings.

Enable recording before starting Codex:

```sh
CODEX_ROLLOUT_TRACE_ROOT="$HOME/.codex/rollout-traces" codex
```

An already-running desktop process does not inherit shell environment changes. On macOS, configure subsequently launched apps for the current login session:

```sh
mkdir -p -m 700 "$HOME/.codex/rollout-traces"
launchctl setenv CODEX_ROLLOUT_TRACE_ROOT "$HOME/.codex/rollout-traces"
```

Fully quit and reopen Codex afterwards. Existing history cannot be captured retroactively.

Register another directory with:

```sh
python3 server/main.py --register /absolute/path/to/recordings
```

Run this command from the plugin directory. Maintenance is available through the backend, outside the viewing surface.

## Inspect

The DSH interface provides turn/step grouping, request boundaries, folding, search, a timeline, virtualized rows, and a resizable inspector. Details include Markdown, code, JSON, prompt/tool diffs, and recorded images. Complete Codex context and original request/response JSON remain separate views.

The panel joins recordings only for the same exact root thread. Resumed tasks preserve prior history and stable identities. Inherited fork history is deduplicated against confirmed ancestors. Compaction shows recorded application state, before/after counts, and opaque items without inventing hidden text. Subtool declarations come from the recording, including unambiguous recorded code-mode TypeScript sections when JSON schema is absent.

The model-facing `show_rollout_trace` tool returns launch metadata. Detailed request and tool bodies are exposed through app-only tools for inspection. These visibility hints depend on the host; they are not an operating-system sandbox.

Theme and language follow the host. Upstream controls support eight locales; Codex-specific text uses Chinese or English fallback.

## Runtime and limits

Python **3.9+**, available as `python3`, and a compatible Codex client are required. No Python packages or Node.js runtime are needed for this built plugin. macOS arm64 has been checked locally; Linux and Windows native integrations remain best effort. Codex CLI 0.163.0 was the original integration baseline, not a minimum-version guarantee.

- Recording schemas: 1 and 2.
- Event-log bound: 256 MiB, including a current-chat aggregate.
- Individual payload bound: 64 MiB.
- Default overview page: 200 execution records.
- Long text is read in 48,000-character chunks; complete copy is available.
- Payload, projection, text, image, and completed-detail caches are bounded. Active reads and selections may consume additional memory.

An exceeded limit is reported explicitly. The reader does not silently present truncated content as complete. Missing continuation prefixes, uncaptured image bytes, opaque compaction text, and unrecorded generation metrics remain unavailable. Original recording files, including `state.json`, are not rewritten.

## Data and privacy

The catalog reads the default `$CODEX_HOME/rollout-traces` directory (default `~/.codex/rollout-traces`), the `CODEX_ROLLOUT_TRACE_ROOT` environment variable, and explicitly registered directories. It does not read the ordinary Codex session archive as a substitute.

Registration writes `$CODEX_HOME/rollout-viewer/config.json`, with a default root under `~/.codex`. The viewer itself does not upload recordings, contact a model, or send telemetry. It provides data to the local host for display; external links and copy/export actions can take content outside that view. Traces may contain credentials and private code. Share only data you have reviewed and redacted.

The optional `python3 server/main.py --preview` server binds to `127.0.0.1` and prints a secret bootstrap URL. It uses a random authenticated cookie and same-origin checks. Treat that URL as a credential. `/harness` tests the MCP Apps bridge locally and does not prove native Codex integration.

The `rollout-viewer` MCP namespace, resource namespace, and configuration keys remain for compatibility with earlier installations.

## Attribution

This project is independently maintained and is **not an official OpenAI or DeepSeek product**. DSH components are MIT licensed, © 2026 DeepSeek. See the included `LICENSE` and `THIRD_PARTY_NOTICES.txt` for project and bundled dependency notices.
