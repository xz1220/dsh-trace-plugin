# Codex Trace

Plugin ID: `codex-dsh-trace@rollout-local`.

A local Codex sidebar app for official `rollout-trace` recordings. The interface
uses DSH's theme and trajectory styles, with a paged execution ledger, timing
overview, reconstructed request context, and tool inspectors.

Version 0.2.19 uses the upstream DSH runtime: turn/step grouping, request boundaries,
three levels of folding, full-content search, interactive timing overview,
virtualized rows, a resizable inspector, Markdown/code/JSON views, prompt/tool
diffs, and the original image gallery. Complete Codex context and original request
and response JSON are additional request tabs. Raw result values remain available
beside rendered content.

The view starts directly with the original DSH toolbar and timeline. Current-chat
binding and live updates are automatic; theme and language follow Codex. There
is no additional navigation row, ellipsis menu, recording selector or settings
panel. Missing recordings show a brief status and keep checking for available
records. Recording maintenance remains available through the local backend and
its command-line interface, outside the chat viewing surface.

The viewer clears ranges on timeline-mode changes, retains shared duration and
wrapping preferences, and keeps tool-to-assistant links available before loading
an assistant body. The launcher accepts an optional `callId` and loads the
required history before selecting it. All eight upstream locales are supported;
Codex-specific panels use Chinese or English fallback.

The current chat is one chronological view across official recordings with the
same exact root. Earlier requests, tools, measured durations and stable row IDs
survive resumed recordings. Historical assistant inputs remain interleaved with
users and retain request-input provenance without invented generation metrics.
Stable identities prevent repeated full snapshots from duplicating old messages.
Source IDs qualify records and call references; raw payloads remain unchanged.
The 256 MiB combined event-log bound is explicit, and source/index caches are
bounded. Both schema 1 and 2 recordings are supported. Unsupported formats show
a reason rather than being silently hidden. Explicit archive inspection remains
available through the backend; the sidebar has no archive-management controls.

The versioned resource URI and an HTML metadata tag identify the frontend build
without adding visible version information to the viewer.

The 0.2.18 name change preserves the `rollout-viewer` MCP namespace, tool API
names, existing recording configuration and saved display preferences. The new
plugin ID is distinct from earlier cached installations.

Version 0.2.19 displays **Codex Trace** with an execution-path composer icon and
light/dark plugin logos. Its plugin ID remains `codex-dsh-trace`. Version 0.2.19
is installed locally and its installed metadata/assets have been checked. The
native panel must be reopened before the new branding can be visually verified.

Subtool Schema inspection prefers the recorded JSON declaration. For code-mode
subtools whose declaration exists only inside the parent request's recorded
`functions.exec` description, it displays that original TypeScript section.
Missing, truncated, namespace-mismatched or ambiguous declarations remain
unavailable. Runtime subtool declarations do not inflate the model tool catalog.

Forked agents keep their own new work visible without replaying the ancestor
conversation into the ledger. Inherited snapshots remain intact in raw request
inspection. Applied compactions show recorded before/after item and role counts;
opaque encrypted items are identified without inventing missing historical text.

## Open

In a Codex conversation's right panel, choose **+ → More tools… → Plugins and
MCPs → Codex Trace**. The native entry joins only official recordings whose
root thread ID matches the caller. If none exist, it shows a brief
empty state. It never substitutes the latest task or asks the user to pick a
recording in the sidebar.

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
through the server's `--register PATH` command.

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

Current bounds: schema versions 1 and 2; 256 MiB event log; 64 MiB individual payload;
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
dragging, copying, navigation and narrow/dark layouts. Version 0.2.9 additionally
repairs the mode-selection, cold parent-link, shared preference and focus-style
differences found by direct upstream comparison. Its installed UI has been
clicked through, including early-call navigation across 301 history records and
all eight host locale notifications. The native panel and schema-2 desktop
recordings have since been observed live. The new top-navigation checks and
native update result are recorded separately in `reports/topbar-0210-validation.json`;
the local preview and bridge harness remain separate evidence. See the
repository's `docs/DSH_PARITY.md`.

## Attribution

Original DSH component styles © 2026 DeepSeek, MIT licensed. See the repository's
`design/DSH-LICENSE.txt` and the license embedded in the bundled HTML. This project
is independently maintained and is not an official OpenAI or DeepSeek product.
