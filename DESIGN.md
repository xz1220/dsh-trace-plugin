# Design system

## Chronological chat continuity, 2026-11-15

Version 0.2.14 keeps the current chat as a stable view across official recordings
whose root matches exactly. Append new records without discarding older requests,
tools, measured timing or the selected inspector. Explicit archive choices stay
pinned. Qualify row and call identities by source and preserve raw payloads.
Bound the aggregate event-log size explicitly; report an exceeded limit and keep
individual captures available. An incomplete new manifest cannot erase history.

Group only adjacent turn/step segments. A repeated label must never move an event
across another segment. Recover historical turn numbers from recorded turn IDs;
the initial global prompt precedes the numbered turns. Historical input messages
retain their own provenance and have no invented generation metrics. Invalidate
projection and detail caches when source history is replaced or prepended.

The menu reports frontend and reader versions independently. Use a versioned UI
resource URI while retaining the legacy alias. Installation checks, local browser
clicks and native Codex acceptance remain distinct evidence categories.

## Historical assistant inputs, 2026-11-15

Version 0.2.12 renders assistant messages already present in recorded request
inputs. Preserve their source order alongside historical users. Keep them in the
history group, apart from the current request's user input and generated response;
they must not become its result anchor. Use recorded identity, role and content
to deduplicate full-snapshot replay without collapsing distinct repeated messages.
Historical input messages have no inferred generation timing or token metrics.

## Startup and live following, 2026-11-15

Version 0.2.11 reads the native entry after initializing its bridge when the host
has not provided a valid launch result. Display the most recent nonempty official
recording for the exact chat while a resumed bundle is empty. Live mode keeps
checking the chat binding after completion, follows new nonempty recordings,
and catches up when the view becomes visible again. Manually selected archives
stay pinned; the menu offers a return to the current chat. Its footer reports the
frontend version so reload state can be checked without another model message.

Preserve the current selection and reading position for ordinary deltas. Revalidate
late host snapshots through the active connection rather than replacing newer data.

## Top navigation alignment, 2026-11-15

Version 0.2.10 removes the sidebar's extra task-title row. The default chrome is
one 36px row containing the active trajectory label and the original DSH ellipsis
icon, followed directly by the unchanged trajectory toolbar and timeline.
Recording selection, refresh, live updates, theme, directory management, language,
agent filtering and statistics belong in the ellipsis popover. Task title and
recording status are visible inside that popover rather than permanently above
the trace. Codex continues to own the conversation surface.

The nonmodal popover supports Escape, outside clicks, keyboard exit, explicit
close and focus restoration. It stays within the viewport and scrolls when the
side panel is short. Directory errors appear inside the open menu. Do not add a
nonfunctional conversation tab to imitate the full DSH chat application.

The 0.2.8 layout description below is historical and is superseded here.

## Running-web alignment, 2026-11-14

Version 0.2.8 uses the user's real DSH Web screenshot as a visual reference. Keep
the 40px task header, 36px trajectory navigation, original 32.5px toolbar,
50.5px timeline and 30px ledger rows. Recording selection is compact on the right;
statistics live in the directory menu. Search announcements do not consume a row.
Show the nested-call fold control only when nested calls exist.

Preserve the original core CSS and scope host focus rules to host-owned controls.
Duration starts with equal-width blocks and shares its saved preference with
code/JSON expansion wrapping. Every mode change clears range selection, including
updates from another app view. Call references must be available in metadata so
cold tool inspection never depends on first reading an assistant body.

The screenshot's full-app chat tabs and account controls belong to the host.
Local recording controls remain available. The default inspector sizing stays
upstream; the final review image used its keyboard resizer to approximate the
reference split. Missing timing values remain unavailable. See
`docs/DSH_PARITY.md` for verification and remaining native-host work.

## Production update, 2026-11-13

The production UI now imports the original DSH runtime from `vendor/dsh`, including
the ledger, toolbar, timeline, Markdown/code/JSON inspectors, icon sprite and theme.
`vendor/dsh/upstream.json` pins the source; `PATCHES.md` documents local extensions.
Core component CSS is unchanged. Host chrome and Codex evidence controls live in
`src/viewer.css`. The prior 12px/72px custom ledger overrides below are historical
and no longer apply to production.

DSH's ledger uses 84px event columns in Chinese and 50px icon columns in narrow
containers. Preserve its 30px rows, request boundary controls, 32px wrapping
toolbar, 50px Overview, resizable inspector and drawer below 760px. Do not restore
the old mock stylesheet as production styling. There is no chat composer in this
sidebar, so its bottom clearance is zero.

Full/known/incremental Codex context, raw request and raw response are additive
request tabs. Record bodies hydrate on selection; loading and errors replace the
inspector body until it is available. Recorded roles, unknown timing, cancellation
prefixes and incomplete context must remain truthful.

## Earlier design notes

The developer reads a trace next to a chat in an ordinary daytime desktop workspace. The current mock uses original DSH theme and trajectory CSS pinned to e8f7b93a344964de3dca1ace9e72b6e4d6de87cb, with light/dark modes and narrow/expanded review surfaces.

- System sans for UI, system monospace for code and timing.
- Ledger and toolbar 12 px / 18 px; inspector tabs 13 px / 20 px; code 12 px / 19 px.
- 32 px toolbar, 50 px timeline, 30 px ledger rows, 34 px detail tab bar, 42 px inspector header. Dividers follow the original 0.5 px declarations.
- Neutral system records, brand-blue user records, green contextual inputs, mixed-purple model records, amber tools and softened amber nested calls. Red indicates failure; status also has text.
- Timeline above a split event ledger and inspector. Default detail width follows clamp(320px, 38%, 440px). Below 760 px, details become an overlay drawer, with an explicit close control. The narrow review mode reproduces this behavior.
- Long request content lives in collapsible source sections. Raw request and resolved context are separate views.
- Prototype data is synthetic and labelled throughout. UI latency targets are design goals, not measured production promises.
- The production sidebar uses 12 px outer gutters, a stable 72 px event column, and 44 px event badges. Ledger text and the timeline track start at 80 px; ledger and inspector headers are both 30 px high. Prompt headings use shared role, preview, inheritance, and character-count columns.

The earlier custom-palette review remains in rollout-viewer.html for comparison; codex-trajectory-dsh.html is the current DSH-based interactive mock.
