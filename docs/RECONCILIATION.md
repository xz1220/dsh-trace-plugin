# Read-only reconciliation

Use `npm run reconcile -- …` to compare an explicitly supplied Codex chat export,
official capture files, and an isolated offline reader. The raw-field oracle does
not use the reader's projection as its truth. It shares only the existing safe
file I/O checks. This is a development tool; it does not inspect the live installed
MCP process or establish native Codex panel compatibility.

## Shared synthetic A/B sample

Run from the repository root with the development dependencies installed:

```sh
npm run reconcile -- fixture --output .cache/reconciliation/sample
npm run reconcile -- check --chat .cache/reconciliation/sample/chat.json --capture .cache/reconciliation/sample/capture --thread-id reconcile-synthetic-thread --output .cache/reconciliation/report-a
npm run reconcile -- fixture --output .cache/reconciliation/sample --append-b
npm run reconcile -- check --chat .cache/reconciliation/sample/chat.json --capture .cache/reconciliation/sample/capture --thread-id reconcile-synthetic-thread --output .cache/reconciliation/report-ab
npm run reconcile -- serve --fixture .cache/reconciliation/sample --port 0
```

The preview prints an authenticated loopback URL. Open that URL first; then open
`/harness?cold=1` on the same origin to exercise the built viewer and MCP Apps bridge.
The server accepts only an owned synthetic fixture. Stop it with Ctrl-C. Fixture
creation preserves nonempty directories; append accepts only its phase-A fixture.

A contains a normal user input, terminal request, stdout/exit code, and final reply.
B contains a delegated `function_call_output`, its own execution and final reply,
and an explicit `previous_response_id` linking to A. The same sample powers Python
regressions and `tests/e2e/reconciliation.spec.mjs`. The browser test checks exact
stdout in tool-result details and exact final messages before and after appending
B, using authenticated preview and a cold bridge harness. It is headless evidence,
not native desktop acceptance.

## Explicit read-only inputs

```sh
npm run reconcile -- check --chat /absolute/chat-export.json --capture /absolute/capture-directory --thread-id exact-thread-id --turn-id exact-turn-A --turn-id exact-turn-B --reader-dir /absolute/plugin/server --output .cache/reconciliation/report
```

- `--chat` accepts the JSON object returned by `read_thread`: `thread.id` plus
  `turns[]`, each with `id`, `status`, and `items[]`.
- `--capture` is repeatable and must name exact capture directories. The tool
  validates every manifest against `--thread-id` before opening any event log or
  payload. It never searches for a nearby chat, scans recording roots, or matches
  items by approximate text.
- `--turn-id` is repeatable; omission selects exactly the turns in the supplied
  export. Only selected-turn payloads may be read, including by the isolated
  reader. Event envelopes from other turns are scanned for sequence validation;
  their payload bodies are not opened. Include the predecessor turn when checking
  continuation context.
- `--reader-dir` defaults to this checkout's `plugins/codex-dsh-trace/server`.
  Supplying an installed directory tests that code in a fresh offline process.
  Reports identify the actual loaded Python file hashes and version-file hash.
  Personal configuration and default recording roots are not read.
- Inputs remain read-only. Output must be a separate empty directory or a report
  directory owned by this tool. No package publication or installation occurs.

The supported verification profile is completed terminal A/B samples: plain-text
`userMessage` or `functionCallOutput` (`create_thread`/`send_message_to_thread`),
`commandExecution`, and `agentMessage` with `phase: final_answer`. IDs align the
chat with raw fields. Final message IDs align to raw responses, then inference IDs
align those responses to projected assistant cells. Original input type/role is
preserved: delegation is context, and does not imply a new user-message row.
Unsupported or missing identities/content, incomplete turns, and insufficient
continuation evidence must remain inconclusive rather than be guessed.

## Reports and exit codes

`report.json` contains scope, provenance, source evidence hashes, counts, and
per-item results. `report.md` is the readable view. Values default to type, byte
length, and SHA-256; full prompts/stdout are not exported into reports. Explicit
input paths and IDs remain in these local reports, so keep real reports private.

| Status               | Meaning                                                                                                                                                  |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `matched`            | Exact value and identity match for the stated layer/field.                                                                                               |
| `bug`                | Chat/raw mismatch, or a reader mismatch/error with independently present source evidence; `layer` identifies which comparison failed.                    |
| `source_missing`     | The explicit readable source lacks the required identity; this does not prove a viewer defect.                                                           |
| `source_unreadable`  | Source safety, format, path, size, or I/O validation failed.                                                                                             |
| `display_difference` | An explicit shell-wrapper representation differs, or delegated context has a different presentation from a user-message row. Stdout is never normalized. |
| `undetermined`       | Wrong scope, unknown identity/shape, incomplete/failed execution, pending write, or insufficient continuation evidence.                                  |

Exit **0** requires only matched or explained display results; **1** means at least
one bug; **2** means insufficient evidence without a confirmed bug. Scope failure
or missing source cannot produce an unconditional pass. A success is bounded to
the supplied snapshot, selected fields, and identified offline reader.
