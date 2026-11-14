# Rollout Viewer

A local Codex sidebar app for official `rollout-trace` recordings. The interface
uses DSH's theme and trajectory styles, with a paged execution ledger, timing
overview, reconstructed request context, and tool inspectors.

Version 0.2.8 uses the upstream DSH runtime: turn/step grouping, request boundaries,
three levels of folding, full-content search, interactive timing overview,
virtualized rows, a resizable inspector, Markdown/code/JSON views, prompt/tool
diffs, and the original image gallery. Complete Codex context and original request
and response JSON are additional request tabs. Raw result values remain available
beside rendered content.

Version 0.2.8 follows the supplied running DSH Web reference with a compact title
and trajectory navigation, conditional nested-call controls, and recording
statistics in the directory menu. It clears ranges on timeline-mode changes,
retains shared duration/wrapping preferences, and keeps tool-to-assistant links
available before loading the assistant body. The launcher accepts an optional
`callId` and loads the required history before selecting it. Core DSH controls
follow the host locale in all eight upstream languages; Codex-specific panels
use Chinese or English fallback.

## Open

In a Codex conversation's right panel, choose **+ → More tools… → Plugins and
MCPs → Rollout Viewer**. The native entry only selects a recording whose root
thread ID matches the caller. Otherwise it offers an explicit recording selector.
It never substitutes the latest task.

The model-facing `show_rollout_trace` tool can also open an explicit trace ID.
It returns only launch metadata. Prompt and tool bodies are loaded through
app-only tools as the user opens them.

## Record

Enable tracing before starting the Codex process:

```sh
CODEX_ROLLOUT_TRACE_ROOT="$HOME/.codex/rollout-traces" codex
```

For a scripted run, the repository includes `scripts/record.py`:

```sh
python3 scripts/record.py -- exec --ephemeral "your task"
```

An already-running desktop process does not inherit a new shell variable.
Desktop recording requires launching that process with the environment variable;
reopening the viewer alone does not enable recording. Existing history cannot be
retroactively captured. The plugin also accepts a recording directory configured
through its empty state or the server's `--register PATH` command.

## Data and performance

- Reads only configured trace roots, not the ordinary Codex session archive.
- Indexes complete JSONL records incrementally. An unchanged poll reads no log bytes.
- First paint uses metadata; large prompt and tool payloads are read on selection.
- Restores WebSocket continuation context from `previous_response_id`, prior
  response output items, and current inputs. Missing prefixes are explicit.
- Text is paged in 48,000-character chunks, with a complete-copy action.
- Requests preserve raw input structure separately from reconstructed context.
- Tool rows link to their code unit and to the first later request containing its
  structured return item, when that evidence exists.
- Request durations are recorded wall-clock boundaries. No token-level latency,
  pure generation time, or readable hidden reasoning is invented.

Current bounds: schema version 1; 256 MiB event log; 64 MiB individual payload;
200 execution records per page. Loaded ledger metadata remains resident and only
visible rows are mounted. Completed detail bodies use a 20-record / 16 MiB cache
budget apart from active reads and selections. Payload, text, projection and image
caches are bounded. A limit error is explicit; full content is never silently
presented as complete after truncation. `state.json` is not rewritten.

Tool content blocks preserve text and image order, including code-cell images.
Business JSON fields named `value` are retained. Image bytes are loaded only from
the recording, with shared decoding, retry, original-image preview and browser
file dragging. Unrecorded image bytes stay unavailable.

## Runtime

Python 3.9+ and Codex are required. No Python packages or network service are
needed. The frontend is bundled into one MCP App resource. Tested on macOS arm64
with Codex CLI 0.163.0. Other client versions may require compatibility updates.

The optional `--preview` server binds only to loopback and requires a random,
HttpOnly, SameSite cookie. It uses the same frontend and data tools as the native
app; `/harness` additionally exercises the MCP Apps postMessage handshake.

Browser reviews cover the image gallery, tool/code/assistant images, actual file
dragging, copying, navigation and narrow/dark layouts. Version 0.2.8 additionally
repairs the mode-selection, cold parent-link, shared preference and focus-style
differences found by direct upstream comparison. Its installed UI has been
clicked through, including early-call navigation across 301 history records and
all eight host locale notifications. Native desktop mounting and new desktop
recordings remain pending; the local preview and bridge harness are separate
evidence. See the repository's `docs/DSH_PARITY.md`.

## Attribution

Original DSH component styles © 2026 DeepSeek, MIT licensed. See the repository's
`design/DSH-LICENSE.txt` and the license embedded in the bundled HTML. This project
is independently maintained and is not an official OpenAI or DeepSeek product.
