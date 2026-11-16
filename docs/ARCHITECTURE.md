# Architecture

Codex Trace reads official Codex `rollout-trace` bundles and exposes them to a local MCP App. It does not invoke a model or reconstruct a recording from ordinary session logs.

## Data path

```text
Codex process → official recording directory
                        ↓
  Catalog → incremental trace index → thread aggregate → projection
                        ↓
              stdio MCP tools and HTML resource
                        ↓
            host bridge → DSH timeline and inspector
```

`server/recording.py` owns file validation, limits, and stable errors. `server/catalog.py` discovers and registers recording roots, keeping per-recording issues visible. `server/bundle_index.py` indexes complete JSONL events, resolves continuation context, and reads payloads lazily. It caches unchanged reads and bounds logs and payloads. A partially written final line waits for a complete event. `server/recorded_content.py` handles message, tool-result, and compaction content. `server/store.py` coordinates these modules as the public reader facade, retaining earlier import paths.

`server/thread_index.py` combines captures for the exact same root thread. Source-qualified row and call identities preserve references across recordings. A resumed empty capture does not erase older history. Confirmed ancestor evidence prevents inherited fork context from being replayed as new work.

`server/projection.py` maps recorded facts to DSH cells, search terms, and detail views. Reconstructed full context is separate from the incremental request actually sent. Compaction state and opaque content are explicit. Historical input messages do not acquire invented generation timing or token usage.

`server/main.py` provides stdio JSON-RPC, MCP tool declarations, and the versioned HTML resource. `server/preview.py` provides the optional authenticated loopback transport through the same dispatcher; its bridge harness is a separate HTML asset. Detailed data tools are marked app-only. A launch tool returns only metadata needed to open the UI. Visibility annotations rely on the host and do not replace file-system permissions.

`src/host.js` handles the MCP Apps bridge. `src/use-chat.js` owns chat selection, paging, and live reads; `src/use-trajectory.js` owns projected records, search, and lazy details. `src/viewer.jsx` and `src/Trajectory.jsx` compose those controllers with the pinned DSH components. Only visible rows are mounted; loading the ledger does not eagerly load every prompt body.

`server/snapshots.py` binds both text APIs to immutable selected content. New readers pass the opaque snapshot token on subsequent pages; eviction reports `content_updated` and the UI can restart the read. An older snapshot can finish after new recording evidence arrives. The cache is bounded by count and estimated bytes; one active selection may exceed the budget. Legacy numeric-version reads remain available.

Chat polling uses the aggregate index directly. Catalog discovery is cached for five seconds; log appends are read on the next visible poll. Late metadata that changes existing projections causes a resync, and unsupported captures remain explicit in aggregate metadata.

## Python protocol implementation

The backend uses Python's standard library so a built local plugin can run without installing Python packages. Its MCP implementation intentionally covers the methods used by this app. Argument validation covers the tool schemas declared here; it is not a general JSON Schema validator. Changes to protocol behavior need protocol tests as well as store tests.

Production startup owns one process-local `Store`. The catalog, indices, projections, and caches use locks for concurrent requests. The dispatcher, stdio handler, and preview factory accept an injected store for isolated tests. Tests use temporary recordings. Further module decomposition should solve a demonstrated maintenance problem rather than add abstractions to the data path.

## Recording and trust boundaries

Schemas 1 and 2 are supported. The reader checks identifiers, known payload layouts, symlinks, hard links, and size limits before reading. These checks reduce accidental or malicious path access; the process still runs with the user's local permissions and is not a security sandbox against a hostile local account. See [SECURITY.md](../.github/SECURITY.md).

Recording files remain read-only. Registering a directory writes only the catalog configuration. The separate recording helper sets an environment variable for a child Codex process or a macOS login session; it does not turn tracing on inside an already-running process.

## Frontend build and provenance

The frontend is bundled into `plugins/codex-dsh-trace/assets/viewer.html`. The source and lockfile are reviewable; the HTML is generated. Builds verify the pinned vendor hashes and documented adaptations before bundling. Generated dependency notices accompany the plugin. `package.json` supplies the version; builds synchronize the plugin manifest and frontend/Python version modules. `npm run check:generated` compares regenerated assets without silently accepting drift. Exact byte comparison uses the canonical Node version in `.nvmrc` and `npm ci`; compression and bundling output can vary between toolchain versions even when supported builds have the same behavior.

`vendor/dsh/upstream.json` pins the upstream commit and original file hashes. `vendor/dsh/patches.json` allows only reviewed adaptations, explained in `vendor/dsh/PATCHES.md`. Core component CSS remains upstream source. Host CSS strengthens the caption color token to meet AA text contrast. Format and lint configuration must exclude vendored source from automatic rewriting.

## Current internal identifiers

The display name is **Codex Trace**. The repository is `dsh-trace-plugin`; the plugin ID remains `codex-dsh-trace`. Earlier `rollout-viewer` identifiers remain in:

- the MCP server key and tool/resource namespace;
- `$CODEX_HOME/rollout-viewer/config.json`;
- saved display-preference keys;
- the legacy `ui://rollout-viewer/viewer.html` resource alias.

These are internal development identifiers, not a public compatibility contract.
The project has not had its first public release and has no migration users.
Before that release, simplify or rename these identifiers directly when needed;
do not build migration paths for internal development installations.

## Verification scope

Unit tests generate isolated recordings, so private captured traces are not required. A local preview exercises the real reader and bundle. A bridge harness exercises MCP Apps messages. Neither establishes that an installed native Codex panel has reloaded or that a particular client version is compatible. Native acceptance must inspect the actual installed panel separately.

## Pinned implementation sources

The original integration used Codex CLI 0.163.0 and source commit `83086188ae0614bd882818ff1aa23f3194962012`: [official rollout-trace source](https://github.com/openai/codex/tree/83086188ae0614bd882818ff1aa23f3194962012/codex-rs/rollout-trace) and [inference recording implementation](https://github.com/openai/codex/blob/83086188ae0614bd882818ff1aa23f3194962012/codex-rs/rollout-trace/src/inference.rs). This is a historical baseline, not a minimum-version guarantee. The plugin reads official recordings directly and has no dependency on third-party session viewers.

DSH runtime source is pinned to `deepseek-ai/deepseek-harness` commit `e8f7b93a344964de3dca1ace9e72b6e4d6de87cb`: [trajectory components](https://github.com/deepseek-ai/deepseek-harness/tree/e8f7b93a344964de3dca1ace9e72b6e4d6de87cb/packages/client/ui-trajectory) and [theme source](https://github.com/deepseek-ai/deepseek-harness/tree/e8f7b93a344964de3dca1ace9e72b6e4d6de87cb/packages/client/ui-theme). The [imported file manifest](../vendor/dsh/upstream.json), [approved patch hashes](../vendor/dsh/patches.json), [adaptation rationale](../vendor/dsh/PATCHES.md), and [upstream license](../vendor/dsh/LICENSE) accompany the source.

These pins describe the implementation baseline; they do not imply that later upstream releases preserve the same APIs or recording formats. Early synthetic prototypes and manual study reports are retained in Git history. Public tests and synthetic fixture generators provide reproducible regression evidence; historical observations do not establish current native-host compatibility.

## Repository entry points

The root README files introduce installation and link to the contribution guide under `.github/`. Architecture, product constraints, and the roadmap are read when needed under `docs/`. Source, tests, maintenance tools, and vendored dependencies have distinct directories. Community policies and release metadata live together under `.github/`; browser configuration stays with its tests and third-party licenses stay under `vendor/`.

Package manifests, lockfiles, ESLint, and editor/Git configuration remain at their conventional discovery locations. Prettier reads its settings from `package.json`. Regenerable local outputs use `.cache/`, with release archives under `dist/`; `local-context/` is reserved for private evidence.
