# Product behavior

Codex Trace helps a Codex user inspect the recorded execution of an agent alongside its conversation. It reads official local `rollout-trace` bundles and does not reconstruct uncaptured history from ordinary session logs.

## The viewing surface

Opening the panel selects the current chat automatically. The DSH toolbar, timeline, event ledger, and inspector provide the primary controls. Theme and language follow the host. New events arrive without a manual refresh; empty states continue checking for records. Recording maintenance belongs in the backend and CLI.

Users can inspect requests, tool calls and returns, nested execution, recorded images, and compaction. Complete reconstructed context and the original incremental request are separate views. Source provenance remains available alongside rendered text.

## Evidence rules

- Show recorded facts and explicitly identify missing information.
- Keep original request and response data intact.
- Preserve earlier readable messages when later context is compacted.
- Do not treat inherited fork context as newly generated conversation.
- Do not assign invented generation timing or token usage to historical input.
- Do not replace an exact current-chat match with a different recent task.

## Responsiveness and accessibility

Large bodies load on selection. Rows are virtualized and indexed incrementally. Ordinary updates preserve selection and reading position. Explicit limits prevent incomplete output from being presented as complete.

The intended interaction supports keyboard operation, visible focus, readable code, text labels alongside color, reduced-motion preferences, and narrow side panels. These are design requirements; passing unit tests alone does not establish full accessibility conformance. Review UI changes with keyboard and assistive-technology checks as appropriate.

## Compatibility

Schema versions 1 and 2 are supported. Native Codex behavior varies by client version; see the [README](../README.md#requirements) for verified scope and [ROADMAP.md](ROADMAP.md) for planned work.
