# Pinned DSH runtime

MIT © 2026 DeepSeek. Imported from `deepseek-ai/deepseek-harness` commit
`e8f7b93a344964de3dca1ace9e72b6e4d6de87cb`. See `LICENSE`.

`upstream.json` records SHA-256 digests of the original files. All component CSS,
theme tokens, Markdown, JSON, icons, timeline gestures, folding and virtualization
are upstream source. `primitives.ts` is a generated barrel containing the exports
used by this application. External dependencies are pinned in the root lockfile.

The following local additions are deliberate and listed in `patches.json`:

- `TrajectoryTable.tsx`: callbacks for selecting requests, a loading/error slot
  for lazy local payloads, and three Codex evidence tabs (complete context, raw
  request, raw response). Skip image dimensions absent from the recording and
  render recorded code-cell images through the existing output-block renderer.
  Request-only anchors use the correct generation/compaction accessibility label.
  Existing DSH tabs and layout are retained.
- `trajectory-record.ts`: typed metadata for lazy records and Codex code cells.
- `code-program.ts`: recognizes the recorded `functions.exec` code cell and its
  original JavaScript source, preserving whitespace and the trailing newline.
- `MessageImage.tsx`: allows unknown dimensions in Codex recordings and resolves
  their display size from the decoded image. The original image gallery, 48px
  contained thumbnail, 64px tile, single-image fitting, retry and lightbox are used.

`node scripts/verify-dsh.mjs` checks the complete imported runtime. Refresh the
source only with `scripts/vendor-dsh.mjs` and an audited upstream checkout; that
command overwrites local patches, which must then be reapplied and reviewed.
