# Product and interface behavior

Codex Trace helps a Codex user inspect recorded agent execution alongside its conversation. It reads official local `rollout-trace` bundles and shows the evidence available in those recordings.

## Viewing and navigation

Opening the panel selects the current chat automatically. The pinned DSH toolbar, timeline, event ledger, and inspector provide the controls; Codex owns the surrounding conversation surface. Theme and language follow the host. Live updates and empty states continue checking for recordings. Recording-directory management and build diagnostics belong in the backend and CLI.

Users can inspect requests, tool calls and returns, nested execution, recorded images, and compaction. Reveal long content on selection. Preserve the selected record, reading position, and source references during ordinary updates. Group adjacent turn/step segments without reordering repeated labels. Start directly with the toolbar and timeline, without an additional branded header or settings row.

## Recorded evidence

- Show recorded facts and identify missing information explicitly. Keep original request and response payloads intact.
- Separate reconstructed complete context, incremental request input, and response output. Ordinary session logs cannot supply uncaptured recording history.
- Preserve earlier readable messages after compaction. Report application state, before/after counts, and opaque items without inventing plaintext from encrypted content.
- Treat inherited fork context as historical input. It must not become new conversation output, a generation result anchor, or a source of invented timing and token usage.
- Match the exact current chat; do not substitute a different recent task.
- Prefer recorded JSON tool declarations. A subtool may use an unambiguous original TypeScript section from the same parent request. Missing or ambiguous declarations remain unavailable.
- Keep uncaptured images, missing continuation prefixes, and unavailable timing explicit. Exceeded limits and unreadable captures in an aggregate must not appear as complete output.
- Bind paged reads and complete copies to the selected content snapshot. New evidence may update the view while an existing snapshot finishes consistently.

## Responsiveness and accessibility

Rows are virtualized and indexed incrementally. Large bodies load on selection. The interface supports keyboard operation, visible focus, readable code, text labels alongside color, reduced-motion preferences, and narrow side panels.

Review UI changes at narrow and wide widths in both themes, with keyboard focus, reduced motion, long code and JSON, images, empty states, transient errors, and live appends. Automated accessibility checks supplement manual keyboard and native-host review; unit tests alone do not establish accessibility conformance.

## Identity and upstream design

The panel title is **Codex Trace**, the repository is `dsh-trace-plugin`, and the plugin ID is `codex-dsh-trace`. Compatibility identifiers are documented in [ARCHITECTURE.md](ARCHITECTURE.md#compatibility-identifiers).

The icon connects three execution nodes with a rounded path and highlights the current endpoint. Its light palette is graphite `#181C1B`, white `#F4F7F6`, and mint `#64DFC2`; its dark-surface palette is `#F0F5F3`, `#18231F`, and `#087C65`. The composer icon is 64 px and logos are 256 px. Avoid lettering and fine details that disappear at small sizes.

[scripts/build-brand-assets.mjs](../scripts/build-brand-assets.mjs) is the source for both SVG and PNG assets. Change that script and run `node scripts/build-brand-assets.mjs`; editing generated files under the plugin's `assets/` directory will be overwritten.

Keep imported DSH component CSS and theme tokens intact. Record source adaptations in [vendor/dsh/PATCHES.md](../vendor/dsh/PATCHES.md) and its approved hashes. Follow [the update procedure](../CONTRIBUTING.md#update-dsh) when changing upstream source.

## Compatibility

Schema versions 1 and 2 are supported. Native Codex behavior varies by client version; see the [README](../README.md#requirements) for verified scope and [ROADMAP.md](ROADMAP.md) for planned work.
