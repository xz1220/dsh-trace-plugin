# Antigravity adaptation worktree

This checkout is dedicated to Antigravity plugin adaptation on
`codex/antigravity-plugin`. Read `docs/ANTIGRAVITY.md` and the latest section of
`HANDOFF.md` before implementation.

## Branch boundaries

- Keep all task edits and commits on `codex/antigravity-plugin`.
- Bring changes from local `main` and `origin/main` into this branch. Do not
  check out, commit to, merge into, or push `main` from this worktree.
- Do not open a merge PR, delete this branch, or remove this worktree unless
  the user asks. The adaptation remains separate until the user authorizes
  integration.
- Preserve user edits and in-progress Git operations. Inspect status before
  synchronizing; do not reset, clean, force-push, or rewrite published history.
- Fetch before comparing branches. Prefer normal merges into this branch so
  incoming main changes and published adaptation commits retain their history.
- After a meaningful change, run the relevant checks, commit only the task's
  files, and push only `codex/antigravity-plugin` to `origin`.

## Adaptation scope

- Reuse the existing DSH UI and trace reader; put Antigravity packaging and
  host-specific integration in a separate adapter.
- Preserve upstream DSH files and documented patches. Keep recording setup
  outside the viewing surface.
- Distinguish the Antigravity UI host from the recording data source. An
  Antigravity conversation ID is not a Codex thread ID.
- Never substitute the newest unrelated recording for a missing binding, or
  represent ordinary session logs as complete recorded model requests.
- Track native Antigravity data investigation separately from the existing
  Codex rollout-trace parser. Document evidence and unsupported fields rather
  than inventing context, timings, or tool relationships.
- Local protocol tests and browser previews do not establish native
  Antigravity acceptance. Record native verification separately.
