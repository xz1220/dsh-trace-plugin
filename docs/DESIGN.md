# Interface and visual design

The interface follows the pinned DSH trajectory components: toolbar, timeline, execution ledger, and inspector. Codex owns the surrounding conversation surface. Local adaptations add recorded-context views and lazy data access rather than a second application shell.

## Panel layout

Start with the original DSH toolbar and timeline. Do not add an extra branded header or a settings row. Current-chat selection, host theme/language, and live following are automatic. Keep recording-directory management and build diagnostics outside the viewing surface.

Reveal long content when the user selects a record. Preserve the selected record, scroll position, and source references as new data arrives. Group only adjacent turn/step segments; repeated labels must not reorder recorded events.

## Content and provenance

Clearly separate full reconstructed context, incremental request input, and response output. Recorded historical inputs retain their provenance and do not become the current generation's response anchor. Raw views preserve the original payload.

For subtools, prefer the recorded JSON declaration. A code-mode declaration may use the original unambiguous TypeScript section from the same parent request. Missing or ambiguous declarations remain unavailable; today's tool definition is not a substitute for a historical declaration.

Compaction details identify application state, before/after counts, and opaque items. The UI must not invent plaintext from encrypted content. Uncaptured images and unavailable timing remain explicit.

## Identity

The panel title is **Codex Trace**; the repository is `dsh-trace-plugin` and the plugin slug is `codex-dsh-trace`. DSH names the upstream interface source. Compatibility identifiers remain documented in [ARCHITECTURE.md](ARCHITECTURE.md#compatibility-identifiers).

The icon is a continuous rounded execution path joining three nodes. The current endpoint uses mint. The primary mark uses graphite `#181C1B`, white `#F4F7F6`, and mint `#64DFC2`. The dark-surface logo uses a light tile `#F0F5F3`, dark path `#18231F`, and teal endpoint `#087C65`.

Editable SVG and generated PNG assets live in the plugin's `assets/` directory. The composer icon is 64 px and logos are 256 px. Regenerate them with `node scripts/build-brand-assets.mjs`. Avoid lettering and fine details that disappear at small sizes.

## Upstream integrity

Keep imported component CSS and theme tokens intact. Record any source adaptation in `vendor/dsh/PATCHES.md` and its approved hashes. See [CONTRIBUTING.md](../CONTRIBUTING.md#update-dsh) before updating vendor source.

## Review requirements

Check narrow/wide layouts, light/dark themes, keyboard focus, reduced-motion behavior, long code and JSON, recorded images, empty states, transient errors, and live appends. Automated accessibility checks supplement manual keyboard and native-host review.

Historical synthetic studies remain in [design/](../design/README.md). Earlier navigation experiments are reference material; they do not override the current direct-to-trajectory design.
