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

// Niche grammars that esbuild would otherwise inline into the single-file IIFE.
// Pruned languages fall back cleanly to plain monospace text in DSH's highlighter.
// Keep `go` and `perl` intact because DSH's highlight.ts patches them on load.
const PRUNED_SHIKI_GRAMMARS = new Set([
  'asciidoc',
  'bibtex',
  'clojure',
  'elixir',
  'erlang',
  'fsharp',
  'groovy',
  'haskell',
  'julia',
  'latex',
  'less',
  'mdx',
  'r',
  'rst',
  'scala',
  'svelte',
  'system-verilog',
  'vb',
  'verilog',
  'vue',
]);

const katexWoff2OnlyPlugin = {
  name: 'katex-woff2-only',
  setup(pluginBuild) {
    pluginBuild.onLoad(
      { filter: /[/\\]katex[/\\]dist[/\\]katex(?:\.min)?\.css$/ },
      async (args) => {
        const source = await readFile(args.path, 'utf8');
        const stripped = source.replace(
          /,\s*url\([^)]+\.(?:woff|ttf)\)\s*format\(["'](?:woff|truetype)["']\)/g,
          '',
        );
        if (/\.(?:woff|ttf)\b/.test(stripped) || !/\.woff2\b/.test(stripped)) {
          throw new Error(
            'Unexpected KaTeX @font-face structure while stripping legacy font formats.',
          );
        }
        return { contents: stripped, loader: 'css', resolveDir: path.dirname(args.path) };
      },
    );
  },
};

const pruneNicheShikiGrammarsPlugin = {
  name: 'prune-niche-shiki-grammars',
  setup(pluginBuild) {
    pluginBuild.onResolve({ filter: /^@shikijs\/langs\/.+$/ }, (args) => {
      const name = args.path.slice('@shikijs/langs/'.length);
      if (!PRUNED_SHIKI_GRAMMARS.has(name)) return null;
      return { path: args.path, namespace: 'pruned-shiki-lang' };
    });
    pluginBuild.onLoad({ filter: /.*/, namespace: 'pruned-shiki-lang' }, () => ({
      contents: 'export default [];',
      loader: 'js',
    }));
  },
};

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
    plugins: [katexWoff2OnlyPlugin, pruneNicheShikiGrammarsPlugin],
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
    loader: { '.woff2': 'dataurl' },
    define: { 'process.env.NODE_ENV': '"production"' },
  });
  const js = result.outputFiles
    .find((f) => f.path.endsWith('.js'))
    .text.replaceAll('</script', '<\\/script');
  const css = result.outputFiles.find((f) => f.path.endsWith('.css')).text;
  const license = await readFile('vendor/dsh/LICENSE', 'utf8');
  const html = `<!doctype html>\n<!-- DSH component styles: ${license} -->\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="rollout-viewer-version" content="${version}"><title>Codex Trace</title><style>${css}</style></head><body><div id="root"></div><!--BOOTSTRAP--><script>${js}</script></body></html>`;
  const files = new Map([
    ...brandAssets(),
    ...(await trajectoryLocaleAssets()),
    ['plugins/codex-dsh-trace/LICENSE', await readFile('LICENSE', 'utf8')],
    ['plugins/codex-dsh-trace/THIRD_PARTY_NOTICES.txt', await thirdPartyNotices(result.metafile)],
    ['plugins/codex-dsh-trace/assets/viewer.html', html],
  ]);
  await updateGeneratedFiles(files, { check });
  console.log(
    `${check ? 'Verified' : 'Built'} Codex Trace MCP App ${version} (${(Buffer.byteLength(html) / (1024 * 1024)).toFixed(2)} MiB viewer.html) and generated assets`,
  );
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await buildPlugin({ check: process.argv.includes('--check') });
}
