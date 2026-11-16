import { readFile, readdir } from 'node:fs/promises';
import path from 'node:path';

const compare = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
const licenseName = /^(?:licen[cs]e|notice|copying|copyright|unlicense)(?:[._-].*)?$/i;

async function licenseFiles(directory, prefix = '') {
  const files = [];
  for (const entry of (await readdir(directory, { withFileTypes: true })).sort((a, b) =>
    compare(a.name, b.name),
  )) {
    if (entry.isSymbolicLink() || entry.name === 'node_modules' || entry.name.startsWith('.'))
      continue;
    const relative = path.posix.join(prefix, entry.name);
    const absolute = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...(await licenseFiles(absolute, relative)));
    else if (entry.isFile() && licenseName.test(entry.name))
      files.push([relative, await readFile(absolute, 'utf8')]);
  }
  return files;
}

function packageRoot(input) {
  const normalized = input.replaceAll('\\', '/');
  const match = /(?:^|\/)node_modules\/((?:@[^/]+\/)?[^/]+)/g;
  let found;
  for (const item of normalized.matchAll(match)) found = item;
  return found ? normalized.slice(0, found.index + found[0].length) : null;
}

// Font metadata remains present in KaTeX's unmodified TTF files even though its
// npm package omits a standalone OFL text. Read it rather than inventing credits.
function fontNotices(buffer) {
  const count = buffer.readUInt16BE(4);
  for (let table = 0; table < count; table++) {
    const entry = 12 + table * 16;
    if (buffer.toString('ascii', entry, entry + 4) !== 'name') continue;
    const offset = buffer.readUInt32BE(entry + 8);
    const records = buffer.readUInt16BE(offset + 2);
    const strings = offset + buffer.readUInt16BE(offset + 4);
    const notices = new Set();
    for (let record = 0; record < records; record++) {
      const at = offset + 6 + record * 12;
      const platform = buffer.readUInt16BE(at);
      const name = buffer.readUInt16BE(at + 6);
      if (![0, 13, 14].includes(name)) continue;
      const length = buffer.readUInt16BE(at + 8);
      const start = strings + buffer.readUInt16BE(at + 10);
      const bytes = Buffer.from(buffer.subarray(start, start + length));
      notices.add(
        platform === 0 || platform === 3
          ? bytes.swap16().toString('utf16le')
          : bytes.toString('latin1'),
      );
    }
    return [...notices].sort(compare).join('\n\n');
  }
  throw new Error('Bundled font has no name table.');
}

export async function thirdPartyNotices(metafile) {
  const used = new Set();
  for (const output of Object.values(metafile.outputs)) {
    for (const [input, metadata] of Object.entries(output.inputs)) {
      if (metadata.bytesInOutput > 0) used.add(input);
    }
  }
  const fonts = Object.keys(metafile.inputs).filter((input) => /\.(?:ttf|woff2?)$/.test(input));
  for (const font of fonts) used.add(font);
  const packages = [...new Set([...used].map(packageRoot).filter(Boolean))].sort(compare);
  const sections = [
    'Third-party software included in Codex Trace',
    'Generated from the esbuild output dependency graph by scripts/third-party-notices.mjs.',
    'Each component remains under its own license. This file includes the full license and notice files supplied by bundled npm packages.',
    'The Codex Trace project license is distributed separately as LICENSE.',
    `DeepSeek Harness (vendored UI components)\nSource: https://github.com/deepseek-ai/deepseek-harness\nCommit: ${JSON.parse(await readFile('vendor/dsh/upstream.json', 'utf8')).commit}\n\n${(await readFile('vendor/dsh/LICENSE', 'utf8')).trim()}`,
  ];
  for (const directory of packages) {
    const metadata = JSON.parse(await readFile(path.join(directory, 'package.json'), 'utf8'));
    const files = await licenseFiles(directory);
    if (!files.length)
      throw new Error(`No license text found for bundled package ${metadata.name}.`);
    const repository =
      typeof metadata.repository === 'string' ? metadata.repository : metadata.repository?.url;
    sections.push(
      [
        `${metadata.name}@${metadata.version}`,
        `License: ${typeof metadata.license === 'string' ? metadata.license : JSON.stringify(metadata.license)}`,
        repository ? `Source: ${repository}` : '',
        ...files.map(([file, content]) => `\n--- ${file} ---\n${content.trim()}`),
      ]
        .filter(Boolean)
        .join('\n'),
    );
  }
  if (fonts.length) {
    if (
      fonts.some((font) => !font.replaceAll('\\', '/').includes('node_modules/katex/dist/fonts/'))
    ) {
      throw new Error('A new bundled font requires a reviewed font license entry.');
    }
    const originals = [
      ...new Set(fonts.map((font) => font.replace(/\.(?:woff2?|ttf)$/, '.ttf'))),
    ].sort(compare);
    const credits = [];
    for (const font of originals) {
      const notice = fontNotices(await readFile(font));
      if (!notice.includes('SIL Open Font License, Version 1.1'))
        throw new Error(`Unexpected font license: ${font}`);
      credits.push(`${path.basename(font)}\n${notice}`);
    }
    sections.push(
      `KaTeX mathematical fonts (unmodified)\nLicense: OFL-1.1\nSource: https://github.com/KaTeX/KaTeX\nThe following copyright, license, and reserved font names are read from the original bundled font metadata.\n\n${credits.join('\n\n')}\n\n${(await readFile('licenses/OFL-1.1.txt', 'utf8')).trim()}`,
    );
  }
  return sections.join('\n\n' + '='.repeat(78) + '\n\n') + '\n';
}
