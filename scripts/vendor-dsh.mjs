// Import the upstream runtime dependency closure, with byte-for-byte provenance.
// Usage: node scripts/vendor-dsh.mjs /path/to/deepseek-harness
import { build } from 'esbuild';
import { readFile, writeFile, mkdir, copyFile } from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { verifyVendorSource } from './vendor-source.mjs';

const upstream = path.resolve(process.argv[2] || '.cache/dsh-upstream');
const destination = path.resolve('vendor/dsh');
const { repository, commit } = verifyVendorSource(
  upstream,
  JSON.parse(await readFile(new URL('../vendor/dsh/upstream.json', import.meta.url), 'utf8')),
);
const primitives = {
  'markdown/CodeBlock.tsx': ['CodeBlock'],
  'FileTypeIcon.tsx': ['FileTypeIcon', 'fileExtension'],
  'file-size.ts': ['fileSizeText'],
  'JsonTree.tsx': ['JsonTree'],
  'markdown/MarkdownText.tsx': ['MarkdownText'],
  'markdown/plain-text.ts': ['extractMarkdownPlainText'],
  'StateDot.tsx': ['StateDot'],
  'Tooltip.tsx': ['Tooltip'],
  'clipboard.ts': ['writeClipboard'],
  'ImageLightbox.tsx': ['ImageLightbox'],
  'DraggableImage.tsx': ['DraggableImage'],
  'icons/index.tsx': [
    'ICON_SYMBOLS',
    'IconLoadingOutlineRegular',
    'IconRefreshOutlineRegular',
    'IconCheckOutlineRegular',
    'IconChevronRightOutlineRegular',
    'IconCodeOutlineRegular',
    'IconWrapLinesOutlineRegular',
    'IconCopyOutlineRegular',
    'IconSettingsOutlineRegular',
    'IconSparkleRegular',
    'IconUserOutlineRegular',
    'IconSearchOutlineRegular',
  ],
};
const primitiveRoot = path.join(upstream, 'packages/client/ui-primitives/src');
const barrel = Object.entries(primitives)
  .map(
    ([file, names]) =>
      `export {${names.join(',')}} from ${JSON.stringify(path.join(primitiveRoot, file))};`,
  )
  .join('\n');
const temporary = path.resolve('.cache/dsh-primitives-entry.ts');
await mkdir(path.dirname(temporary), { recursive: true });
await writeFile(temporary, barrel);
const trajectory = path.join(upstream, 'packages/client/ui-trajectory/src/client');
const entry =
  ['TrajectoryTable.tsx', 'TrajectoryTimeline.tsx', 'TrajectoryToolbar.tsx']
    .map((file) => `export * from ${JSON.stringify(path.join(trajectory, file))};`)
    .join('\n') +
  `\nexport {ImageGallery} from ${JSON.stringify(path.join(upstream, 'packages/client/ui-attachment/src/MessageImage.tsx'))};` +
  `\nexport {FileTransfers} from ${JSON.stringify(path.join(upstream, 'packages/client/ui-file-drag/src/client/transfers.ts'))};`;
const aliases = {
  '@deepseek-ai/dsh-client-ui-primitives': temporary,
  '@deepseek-ai/dsh-util-values': path.join(upstream, 'packages/util/values/src/index.ts'),
  '@deepseek-ai/dsh-util-code-language': path.join(
    upstream,
    'packages/util/code-language/src/index.ts',
  ),
  '@deepseek-ai/dsh-util-workspace-path': path.join(
    upstream,
    'packages/util/workspace-path/src/index.ts',
  ),
  '@deepseek-ai/dsh-util-file-drag': path.join(upstream, 'packages/util/file-drag/src/index.ts'),
  '@deepseek-ai/dsh-util-crypto': path.join(upstream, 'packages/util/crypto/src/index.ts'),
};
const result = await build({
  stdin: { contents: entry, resolveDir: process.cwd(), loader: 'ts' },
  bundle: true,
  write: false,
  metafile: true,
  outdir: '.cache/vendor-probe',
  jsx: 'automatic',
  packages: 'external',
  alias: aliases,
});
const files = Object.keys(result.metafile.inputs)
  .map((file) => path.resolve(file))
  .filter((file) => file.startsWith(upstream + path.sep));
// Theme is part of the rendered component, not a substitute palette.
for (const file of ['base.css', 'design-platform.css', 'focus.css', 'gradient-shadow-text.css']) {
  files.push(path.join(upstream, 'packages/client/ui-theme/src/styles', file));
}
for (const file of ['locales.ts', 'views.module.css']) files.push(path.join(trajectory, file));
files.push(path.join(upstream, 'packages/client/ui-theme/src/client/icon-sprite.ts'));
for (const language of ['zh', 'en', 'ja', 'es', 'fr', 'de', 'ru', 'pt'])
  files.push(path.join(upstream, `packages/client/locale/src/locales/${language}.ts`));
const manifest = { repository, commit, files: [] };
for (const source of [...new Set(files)].sort()) {
  const relative = path.relative(upstream, source);
  const target = path.join(destination, relative);
  await mkdir(path.dirname(target), { recursive: true });
  await copyFile(source, target);
  const bytes = await readFile(source);
  manifest.files.push({ path: relative, sha256: createHash('sha256').update(bytes).digest('hex') });
}
await copyFile(path.join(upstream, 'LICENSE'), path.join(destination, 'LICENSE'));
const localBarrel =
  Object.entries(primitives)
    .map(
      ([file, names]) =>
        `export {${names.join(',')}} from './packages/client/ui-primitives/src/${file}';`,
    )
    .join('\n') + '\n';
await writeFile(path.join(destination, 'primitives.ts'), localBarrel);
await writeFile(path.join(destination, 'upstream.json'), JSON.stringify(manifest, null, 2) + '\n');
const packages = [
  ...new Set(
    Object.values(result.metafile.inputs).flatMap((input) =>
      input.imports.filter((item) => item.external).map((item) => item.path),
    ),
  ),
];
console.log(JSON.stringify({ files: files.length, externalPackages: packages }, null, 2));
