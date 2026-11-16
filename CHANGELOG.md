# Changelog

User-visible changes are recorded here. Historical entries describe code changes, not whether a particular local Codex panel reloaded successfully.

## Unreleased

### Added

- Direct Git marketplace installation and update commands, with recording setup that works without a source checkout.
- Public installation, privacy, architecture, contribution, security, and roadmap documentation.
- CI, formatting, linting, Python type checks, and generated-asset verification.
- An isolated synthetic demo, browser/accessibility regressions, and protocol tests.
- A version synchronization build step, bundled dependency notices, and ZIP packaging with checksums.

### Fixed

- Keep paged context and cell reads on an immutable content snapshot during live updates.
- Refresh projections after late agent/turn metadata and report unreadable captures in a chat aggregate.
- Isolate malformed manifests so one invalid recording does not stop catalog discovery.
- Build large selected details once for all text pages.

- Isolate authenticated preview cookies by port so concurrent previews do not overwrite each other.
- Allow protocol and preview tests to inject an isolated store.
- Preserve request-button activation with Enter and Space, and improve text contrast in both themes.
- Return stable error codes and localize UI errors through shared Chinese/English dictionaries.
- Keep live-fixture resets and appends on the original recording schema.

### Changed

- Reduce root entries by grouping contribution/security policies and release settings under `.github/`, browser configuration with its tests, and asset licenses under `vendor/`.
- Consolidate regenerable check and browser outputs under `.cache/` and add a local cleanup command.

- Separate recording/catalog, preview transport, and frontend data controllers.
- Reuse catalog scans during chat polling and retain unaffected detail caches.
- Verify the pinned clean upstream checkout before importing vendor source.
- Share synthetic test fixtures and make installation checks independent of recording completion.

- Remove historical design prototypes and unused runtime state; consolidate product and source documentation.

- Rename the repository to `dsh-trace-plugin`, retaining the existing plugin ID and display name.
- Archived machine-specific handoff notes and one-off validation logs outside the tracked source tree.

## 0.2.19 — 2026-11-16

### Changed

- Use **Codex Trace** as the display name, with an execution-path icon and light/dark logos.
- Retain `codex-dsh-trace` as the repository and plugin ID.

## 0.2.18 — 2026-11-16

### Changed

- Rename the project and plugin distribution to `codex-dsh-trace`.
- Preserve existing `rollout-viewer` MCP identifiers, recording configuration, and preference keys for compatibility.

## 0.2.17 — 2026-11-16

### Fixed

- Display recorded code-mode subtool declarations when an unambiguous original TypeScript declaration is available.
- Deduplicate inherited fork history against confirmed ancestors while retaining new child work and raw inputs.
- Explain applied compaction snapshots, before/after role counts, and opaque content without fabricating historical text.

## 0.2.16 — 2026-11-15

### Changed

- Open directly into the DSH toolbar and timeline with automatic current-chat binding and live updates.
- Keep recording maintenance in the backend and CLI rather than in the viewing surface.

## 0.2.14 — 2026-11-15

### Added

- A stable chronological view across official captures for the same exact root thread.
- Source-qualified identities, bounded aggregate history, and explicit errors for oversized logs.

### Fixed

- Preserve earlier requests, tools, durations, selection, and adjacent turn grouping across resumed recordings.

## 0.2.12 — 2026-11-15

### Fixed

- Render recorded historical assistant inputs alongside historical users, with stable identities and original provenance.
- Keep historical inputs separate from the current response's timing and token metrics.

## 0.2.11 — 2026-11-15

### Fixed

- Read the current chat on startup without waiting for another model message.
- Discover new captures after completion and retain prior content while a resumed capture is empty.

## 0.2.9 — 2026-11-14

### Fixed

- Support schema 2 recordings and explicitly report unsupported formats.
- Align timeline-mode selection, cold parent navigation, duration/wrapping preferences, and focus handling with the upstream interface.

Earlier development introduced the pinned DSH interface, lazy payload inspection, local authenticated preview, recorded images, and incremental indexing. This is a curated history of notable changes, not an exhaustive record of every development version.
