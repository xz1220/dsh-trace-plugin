# Codex Rollout Viewer

Native Codex sidebar plugin for official rollout-trace, using the approved
DSH-style interface. It shows complete recorded client context, original
incremental requests, tool input/output and caller relationships, and timing.

## Run and install

```sh
npm ci
npm run build
npm test
codex plugin marketplace add /absolute/path/to/codex-rollout-viewer
codex plugin add rollout-viewer@rollout-local
```

Open **Rollout Viewer** from the conversation's right-panel tools menu. Select a
recording explicitly if the current conversation has no matching trace.
Newly installed plugins may require reopening the conversation or restarting the
desktop app before their entrypoints appear.

Record a new CLI task with `python3 scripts/record.py -- exec --ephemeral "task"`.
For existing recordings, add their directory in the viewer. Recording must be
enabled before a task starts; ordinary session logs are not silently substituted.
See [plugin documentation](plugins/rollout-viewer/README.md) for runtime and limits.

On macOS, `python3 scripts/record.py --desktop-env` sets the official recording
environment variable for subsequently launched desktop apps in the current login
session. Fully quit and reopen Codex afterwards. It does not close the current app
or make changes to existing recordings. After logging out, run it again if needed.
Use `launchctl unsetenv CODEX_ROLLOUT_TRACE_ROOT` and restart Codex to turn it off.

## Validation

- Real OpenAI task: three model requests, two terminal tool calls, two code cells.
- Base/developer/workspace/user instructions and tool returns recovered completely.
- Request context item counts agree with the official `codex debug trace-reduce` output.
- MCP discovery, exact native-thread binding, UI resource, and MCP Apps browser handshake checked.
- Backend tests cover continuation, partial writes, paging, immutable warm reads,
  missing context, Unicode chunks, and invalid payload paths.
- Redacted benchmark results are in `reports/performance.json`; no captured prompts
  or real trace bundles are committed.
- Installed-package RPC checks are reproducible with `scripts/verify-install.py`.
- Native desktop mounting still needs verification after the app reloads the newly
  installed plugin. The same installed UI is verified in a browser and MCP Apps
  handshake harness; these checks do not substitute for that final host check.

The optional local preview uses the installed MCP App frontend and backend,
with a private loopback cookie. It is not a mock data implementation.

## Current interactive mock

Open `design/codex-trajectory-dsh.html` for the DSH-style Codex sidebar prototype.
The three guided paths inspect full prompts, trace tool calls, and select timing
intervals. Full/incremental context, original request JSON, source filtering,
tool arguments/results/schema, parent/child navigation, wheel zoom, range
selection, folding, simulated playback, error states, and narrow/dark views work
locally. All data is synthetic; no local sessions or model APIs are accessed.

Build with `npm run build:mock`. Original DSH CSS is hash-verified by the same
source cache used for the analysis. The generated HTML is self-contained.

## Source design-system analysis

The current review deliverable is `design/dsh-design-system.html`: a self-contained,
source-backed decomposition of the DSH trajectory design system. It includes
original CSS specimens, theme tokens, type/size specifications, conditional detail
tabs, interactions, responsive behavior, performance mechanisms, and pinned source
links. Demonstration content is synthetic and clearly distinguished from source
facts and analysis.

Build this study with `npm ci && npm run build:analysis`. The build verifies and
caches upstream sources using Git blob SHA-1 values in `design/dsh-sources.json`.
Source copies are excluded from Git; the output HTML works without a server or
network. See `design/DSH-NOTICE.md` and `design/DSH-LICENSE.txt` for attribution.

## Earlier Codex plugin mock

An interactive design review for a future native Codex sidebar plugin based on official rollout-trace.

Open `design/rollout-viewer.html` directly in a browser. It is self-contained, works offline, and contains only synthetic demonstration data.

The review includes:
- An interactive event ledger, timeline, and request/tool inspector.
- Full-context versus incremental-request views.
- Completed, failed, missing-context, and unrecorded scenarios.
- User journeys and a visible design system.
- Light/dark themes, compact/comfortable density, and narrow/expanded previews.

Build with `npm ci && npm run build:design`.

This is a frontend prototype. It does not read local sessions, invoke a model, enable recording, or install a plugin.
