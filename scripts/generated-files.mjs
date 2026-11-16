import { readFile, writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';

// Check without rewriting files so CI catches every committed build artifact.
export async function updateGeneratedFiles(files, { check = false } = {}) {
  const stale = [];
  for (const [file, content] of files) {
    const expected = Buffer.isBuffer(content) ? content : Buffer.from(content);
    const actual = await readFile(file).catch((error) => {
      if (error.code !== 'ENOENT') throw error;
      return null;
    });
    if (actual?.equals(expected)) continue;
    stale.push(file);
    if (!check) {
      await mkdir(path.dirname(file), { recursive: true });
      await writeFile(file, expected);
    }
  }
  if (check && stale.length) {
    throw new Error(`Generated files are stale. Run npm run build:\n${stale.join('\n')}`);
  }
  return stale;
}
