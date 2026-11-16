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

`server/store.py` discovers recording roots, validates paths, indexes complete JSONL events, resolves continuation context, and reads payloads lazily. It caches unchanged reads and bounds logs and payloads. A partially written final line waits for a complete event.

`server/thread_index.py` combines captures for the exact same root thread. Source-qualified row and call identities preserve references across recordings. A resumed empty capture does not erase older history. Confirmed ancestor evidence prevents inherited fork context from being replayed as new work.

`server/projection.py` maps recorded facts to DSH cells, search terms, and detail views. Reconstructed full context is separate from the incremental request actually sent. Compaction state and opaque content are explicit. Historical input messages do not acquire invented generation timing or token usage.

`server/main.py` provides stdio JSON-RPC, MCP tool declarations, the versioned HTML resource, and an optional authenticated loopback preview. Detailed data tools are marked app-only. A launch tool returns only metadata needed to open the UI. Visibility annotations rely on the host and do not replace file-system permissions.

`src/host.js` handles the MCP Apps bridge. `src/viewer.jsx` coordinates current-chat binding, live reads, preferences, and lazy details. `src/Trajectory.jsx` adapts backend records to the pinned DSH components. Only visible rows are mounted; loading the ledger does not eagerly load every prompt body.

## Python protocol implementation

The backend uses Python's standard library so a built local plugin can run without installing Python packages. Its MCP implementation intentionally covers the methods used by this app. Argument validation covers the tool schemas declared here; it is not a general JSON Schema validator. Changes to protocol behavior need protocol tests as well as store tests.

Production startup owns one process-local `Store`. The catalog, indices, projections, and caches use locks for concurrent requests. The dispatcher, stdio handler, and preview factory accept an injected store for isolated tests. Tests use temporary recordings. Further module decomposition should solve a demonstrated maintenance problem rather than add abstractions to the data path.

## Recording and trust boundaries

Schemas 1 and 2 are supported. The reader checks identifiers, known payload layouts, symlinks, hard links, and size limits before reading. These checks reduce accidental or malicious path access; the process still runs with the user's local permissions and is not a security sandbox against a hostile local account. See [SECURITY.md](../SECURITY.md).

Recording files remain read-only. Registering a directory writes only the catalog configuration. The separate recording helper sets an environment variable for a child Codex process or a macOS login session; it does not turn tracing on inside an already-running process.

## Frontend build and provenance

The frontend is bundled into `plugins/codex-dsh-trace/assets/viewer.html`. The source and lockfile are reviewable; the HTML is generated. Builds verify the pinned vendor hashes and documented adaptations before bundling. Generated dependency notices accompany the plugin. `package.json` supplies the version; builds synchronize the plugin manifest and frontend/Python version modules. `npm run check:generated` compares regenerated assets without silently accepting drift. Exact byte comparison uses the canonical Node version in `.nvmrc` and `npm ci`; compression and bundling output can vary between toolchain versions even when supported builds have the same behavior.

`vendor/dsh/upstream.json` pins the upstream commit and original file hashes. `vendor/dsh/patches.json` allows only reviewed adaptations, explained in `vendor/dsh/PATCHES.md`. Core component CSS remains upstream source. Host CSS strengthens the caption color token to meet AA text contrast. Format and lint configuration must exclude vendored source from automatic rewriting.

The `design/` directory contains historical studies with synthetic data. Those prototypes are separate build targets and do not read personal recordings. They are not runtime dependencies or native integration evidence.

## Compatibility identifiers

The display name is **Codex Trace**. The repository is `dsh-trace-plugin`; the plugin ID remains `codex-dsh-trace`. Earlier `rollout-viewer` identifiers remain in:

- the MCP server key and tool/resource namespace;
- `$CODEX_HOME/rollout-viewer/config.json`;
- saved display-preference keys;
- the legacy `ui://rollout-viewer/viewer.html` resource alias.

Keeping these identifiers avoids breaking installed clients, saved preferences, and existing launches. There is no scheduled removal. A future breaking migration must provide a documented path and explicit compatibility tests; renaming internal identifiers is not required for the current product name.

## Verification scope

Unit tests generate isolated recordings, so private captured traces are not required. A local preview exercises the real reader and bundle. A bridge harness exercises MCP Apps messages. Neither establishes that an installed native Codex panel has reloaded or that a particular client version is compatible. Native acceptance must inspect the actual installed panel separately.
