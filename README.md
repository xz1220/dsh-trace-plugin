# Codex Rollout Viewer

继续本次工作请先读 [HANDOFF.md](HANDOFF.md)。代码、设计稿、真实录制、实验与运行状态均已整理在本目录；归档原始材料位于 `local-context/`。

Native Codex sidebar plugin for official rollout-trace, using the approved
DSH-style interface. It shows complete recorded client context, original
incremental requests, tool input/output and caller relationships, and timing.

The current implementation is **0.2.14**. Its compact trajectory navigation
follows the user's running DSH Web screenshot: “轨迹 / ···”, followed directly by
the toolbar and timeline. Recording selection, refresh, live updates, theme,
directories, language, agent filtering and statistics are in the “···” menu.
There is no extra task-title row inside the sidebar. It uses the pinned upstream trajectory table, timeline, toolbar,
inspectors and image gallery. Core component CSS remains unchanged; local
adapters are documented in `vendor/dsh/PATCHES.md` and verified during builds.

The follow-up comparison findings are repaired: timeline-mode changes clear
selection, cold tool inspection links to its assistant, duration/wrapping
preferences survive recording switches and reloads, and host focus styles stay
out of the DSH search field. Call-ID launch requests load the necessary history;
core controls follow all eight upstream locales. Local Codex extensions use
Chinese or English fallback.

The sidebar actively reads its current-chat recording when opened, without
waiting for another model message. The current-chat view joins official
recordings for the same exact root and keeps earlier requests, tools, timing and
message order while new recordings appear. Explicitly selected archives remain
pinned. “Return to this chat” restores automatic following.
The regression evidence is in `reports/startup-live-0211-validation.json`;
current chronological-history evidence is in `reports/chronology-0214-validation.json`.

Recorded assistant messages replayed inside a request are now visible alongside
historical users. Stable message identities prevent duplicate replay rows while
keeping distinct new messages with identical text. Historical input messages have
their own group and source; they are not presented as the current inference's
response or assigned its token usage and timing. The regression evidence is in
`reports/history-assistant-0212-validation.json`.

**81 automated checks pass.** Current chronology clicks cover three- and four-turn
updates on the 0.2.13 functional candidate; installed 0.2.14 file/RPC checks cover
the final release. Earlier installed builds also cover 301-record call navigation,
copying, image export, locale notifications and 360px dark layouts. Native Codex
acceptance of this release remains pending an updated, expanded app connection.
[The current acceptance ledger](docs/DSH_PARITY.md) and
`reports/dsh-alignment-028.json` record the earlier interaction evidence. The native
panel has been observed live, and after the user's restart the connected backend
reads schema 1/2 recordings. Version 0.2.9 fixed the schema-2 compatibility bug
and explicitly reports unreadable formats. The 0.2.10 top-navigation acceptance
and native verification are recorded separately in `reports/topbar-0210-validation.json`;
local preview is not evidence of an updated native panel.

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
For existing recordings, open “···” to choose a recording or add its directory. Recording must be
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
  missing context, Unicode chunks, invalid payload paths, 1,100-request chains,
  namespaced schemas, cancellation prefixes, images, and structured result values.
- Redacted benchmark results are in `reports/performance.json`; no captured prompts
  or real trace bundles are committed.
- Installed-package RPC checks are reproducible with `scripts/verify-install.py`.
- Current DSH integration checks and backend timings are in
  `reports/dsh-installed-validation.json` and `reports/dsh-performance.json`.
  Browser evidence and remaining UI gates are in `reports/dsh-parity-validation.json`.
- Native 0.2.9 mounting and schema-2 reading have been observed. The 0.2.10
  navigation still needs verification after the desktop reloads its old plugin
  connection. Installed preview checks do not substitute for that host result.

The optional local preview uses the installed MCP App frontend and backend,
with a private loopback cookie. It is not a mock data implementation.

## Earlier interactive mock

Open `design/codex-trajectory-dsh.html` for the DSH-style Codex sidebar prototype.
The three guided paths inspect full prompts, trace tool calls, and select timing
intervals. Full/incremental context, original request JSON, source filtering,
tool arguments/results/schema, parent/child navigation, wheel zoom, range
selection, folding, simulated playback, error states, and narrow/dark views work
locally. All data is synthetic; no local sessions or model APIs are accessed.

Build with `npm run build:mock`. Original DSH CSS is hash-verified by the same
source cache used for the analysis. The generated HTML is self-contained.

## Source design-system analysis

The earlier design-system study is `design/dsh-design-system.html`: a self-contained,
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
