import { build } from 'esbuild';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import './verify-dsh.mjs';
import { trajectoryLocaleAssets } from './sync-trajectory-locales.mjs';
import { brandAssets } from './build-brand-assets.mjs';
import { versionArtifacts } from './sync-version.mjs';
import { updateGeneratedFiles } from './generated-files.mjs';
import { thirdPartyNotices } from './third-party-notices.mjs';

export async function buildPlugin({ check = false } = {}) {
  const { version, files: versionFiles } = await versionArtifacts();
  await updateGeneratedFiles(versionFiles, { check });
  const root = path.resolve('vendor/dsh');
  const result = await build({
    entryPoints: ['src/viewer.jsx'],
    bundle: true,
    write: false,
    minify: true,
    metafile: true,
    format: 'iife',
    jsx: 'automatic',
    outfile: 'plugins/codex-dsh-trace/assets/viewer.js',
    alias: {
      '@deepseek-ai/dsh-client-ui-primitives': path.join(root, 'primitives.ts'),
      '@deepseek-ai/dsh-util-values': path.join(root, 'packages/util/values/src/index.ts'),
      '@deepseek-ai/dsh-util-code-language': path.join(
        root,
        'packages/util/code-language/src/index.ts',
      ),
      '@deepseek-ai/dsh-util-workspace-path': path.join(
        root,
        'packages/util/workspace-path/src/index.ts',
      ),
      '@deepseek-ai/dsh-util-file-drag': path.join(root, 'packages/util/file-drag/src/index.ts'),
      '@deepseek-ai/dsh-util-crypto': path.join(root, 'packages/util/crypto/src/index.ts'),
    },
    loader: { '.woff2': 'dataurl', '.woff': 'dataurl', '.ttf': 'dataurl' },
    define: { 'process.env.NODE_ENV': '"production"' },
  });
  const js = result.outputFiles
    .find((f) => f.path.endsWith('.js'))
    .text.replaceAll('</script', '<\\/script');
  const css = result.outputFiles.find((f) => f.path.endsWith('.css')).text;
  const license = await readFile('vendor/dsh/LICENSE', 'utf8');
  const files = new Map([
    ...brandAssets(),
    ...(await trajectoryLocaleAssets()),
    ['plugins/codex-dsh-trace/LICENSE', await readFile('LICENSE', 'utf8')],
    ['plugins/codex-dsh-trace/THIRD_PARTY_NOTICES.txt', await thirdPartyNotices(result.metafile)],
    [
      'plugins/codex-dsh-trace/assets/viewer.html',
      `<!doctype html>\n<!-- DSH component styles: ${license} -->\n<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="rollout-viewer-version" content="${version}"><title>Codex Trace</title><style>${css}</style></head><body><div id="root"></div><!--BOOTSTRAP--><script>${js}</script></body></html>`,
    ],
  ]);
  await updateGeneratedFiles(files, { check });
  console.log(
    `${check ? 'Verified' : 'Built'} Codex Trace MCP App ${version} and generated assets`,
  );
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await buildPlugin({ check: process.argv.includes('--check') });
}
