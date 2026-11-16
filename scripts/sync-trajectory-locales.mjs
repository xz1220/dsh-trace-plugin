// Keep server-side metadata search terms identical to the displayed upstream labels.
import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { updateGeneratedFiles } from './generated-files.mjs';
export async function trajectoryLocaleAssets() {
  const result = await build({
    entryPoints: [fileURLToPath(new URL('../src/locale.js', import.meta.url))],
    bundle: true,
    write: false,
    format: 'esm',
  });
  const { dictionaries } = await import(
    `data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`
  );
  const data = Object.fromEntries(
    Object.entries(dictionaries).map(([locale, dictionary]) => [
      locale,
      { step: dictionary['group.step'], compaction: dictionary['group.compaction'] },
    ]),
  );
  return new Map([
    [
      'plugins/codex-dsh-trace/server/trajectory-locales.json',
      JSON.stringify(data, null, 2) + '\n',
    ],
  ]);
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await updateGeneratedFiles(await trajectoryLocaleAssets(), {
    check: process.argv.includes('--check'),
  });
}
