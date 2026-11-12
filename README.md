# DSH trajectory design study / Codex Rollout Viewer

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
