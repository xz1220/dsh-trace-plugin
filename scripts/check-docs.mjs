import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, extname, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const SKIP_DIRS = new Set(['.cache', '.git', '.venv', 'dist', 'local-context', 'node_modules']);
const SKIP_RELATIVE_PATHS = new Set([
  'vendor/dsh/packages',
  'packages/dsh-trace-extension/payload',
]);
const EXTERNAL_SCHEME = /^[a-z][a-z0-9+.-]*:/i;

function normalizePosix(value) {
  return value.replaceAll('\\', '/');
}

function stripInlineCode(line) {
  let result = '';
  let index = 0;
  while (index < line.length) {
    if (line[index] !== '`') {
      result += line[index];
      index += 1;
      continue;
    }
    let ticks = 0;
    while (index + ticks < line.length && line[index + ticks] === '`') ticks += 1;
    const close = line.indexOf('`'.repeat(ticks), index + ticks);
    if (close === -1) {
      result += line.slice(index, index + ticks);
      index += ticks;
    } else {
      index = close + ticks;
    }
  }
  return result;
}

function stripHeadingFormatting(text) {
  return text
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/<[^>]+>/g, '')
    .replace(/[*~]/g, '')
    .trim();
}

export function slugifyHeading(text) {
  const cleaned = stripHeadingFormatting(text).toLowerCase();
  let slug = '';
  for (const char of cleaned) {
    if (char === ' ') {
      slug += '-';
    } else if (char === '-' || char === '_' || /[\p{L}\p{N}]/u.test(char)) {
      slug += char;
    }
  }
  return slug;
}

function iterateNonCodeLines(markdown, callback) {
  const lines = markdown.split(/\r?\n/);
  let fenceChar = null;
  let fenceLength = 0;
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    const fenceMatch = line.match(/^\s{0,3}(`{3,}|~{3,})/);
    if (fenceMatch) {
      const marker = fenceMatch[1];
      if (!fenceChar) {
        fenceChar = marker[0];
        fenceLength = marker.length;
        continue;
      }
      if (
        marker[0] === fenceChar &&
        marker.length >= fenceLength &&
        /^\s*$/.test(line.slice(fenceMatch[0].length))
      ) {
        fenceChar = null;
        fenceLength = 0;
        continue;
      }
    }
    if (fenceChar) continue;
    callback(line, i + 1);
  }
}

export function extractHeadings(markdown) {
  const slugs = new Set();
  const counts = new Map();
  iterateNonCodeLines(markdown, (line) => {
    const headingMatch = line.match(/^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$/);
    if (headingMatch) {
      const base = slugifyHeading(headingMatch[1]);
      if (base) {
        const seen = counts.get(base) ?? 0;
        counts.set(base, seen + 1);
        slugs.add(seen === 0 ? base : `${base}-${seen}`);
      }
    }
    for (const match of line.matchAll(/<a\b[^>]*\b(?:id|name)=["']([^"']+)["']/gi)) {
      slugs.add(match[1].trim().toLowerCase());
    }
  });
  return slugs;
}

function parseLinkDestination(raw) {
  const trimmed = raw.trim();
  if (!trimmed) return '';
  if (trimmed.startsWith('<')) {
    const end = trimmed.indexOf('>');
    if (end !== -1) return trimmed.slice(1, end).trim();
  }
  const spaceIndex = trimmed.search(/\s/);
  return spaceIndex === -1 ? trimmed : trimmed.slice(0, spaceIndex);
}

export function extractLinks(markdown) {
  const links = [];
  iterateNonCodeLines(markdown, (line, lineNumber) => {
    const stripped = stripInlineCode(line);
    const refDef = stripped.match(/^\s{0,3}\[[^\]]+\]:\s*(.+)$/);
    if (refDef) {
      const destination = parseLinkDestination(refDef[1]);
      if (destination) links.push({ line: lineNumber, target: destination });
      return;
    }
    let index = 0;
    while (index < stripped.length) {
      const openBracket = stripped.indexOf('[', index);
      if (openBracket === -1) break;
      const closeBracket = stripped.indexOf(']', openBracket + 1);
      if (closeBracket === -1) break;
      if (stripped[closeBracket + 1] !== '(') {
        index = closeBracket + 1;
        continue;
      }
      let cursor = closeBracket + 2;
      let depth = 1;
      while (cursor < stripped.length && depth > 0) {
        if (stripped[cursor] === '\\' && cursor + 1 < stripped.length) {
          cursor += 2;
          continue;
        }
        if (stripped[cursor] === '(') depth += 1;
        else if (stripped[cursor] === ')') depth -= 1;
        cursor += 1;
      }
      if (depth === 0) {
        const rawTarget = stripped.slice(closeBracket + 2, cursor - 1);
        const destination = parseLinkDestination(rawTarget);
        if (destination) links.push({ line: lineNumber, target: destination });
        index = cursor;
      } else {
        index = closeBracket + 2;
      }
    }
  });
  return links;
}

export function collectMarkdownFiles(rootDir = ROOT) {
  const files = [];
  const walk = (directory) => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const fullPath = resolve(directory, entry.name);
      const rel = normalizePosix(relative(rootDir, fullPath));
      if (entry.isDirectory()) {
        if (SKIP_DIRS.has(entry.name) || SKIP_RELATIVE_PATHS.has(rel)) continue;
        walk(fullPath);
      } else if (entry.isFile() && extname(entry.name).toLowerCase() === '.md') {
        files.push(fullPath);
      }
    }
  };
  walk(rootDir);
  files.sort();
  return files;
}

function safeDecode(value) {
  try {
    return decodeURIComponent(value);
  } catch {
    return null;
  }
}

export function checkDocs(rootDir = ROOT) {
  const files = collectMarkdownFiles(rootDir);
  const headingsByFile = new Map();
  const contentsByFile = new Map();
  for (const file of files) {
    const text = readFileSync(file, 'utf8');
    contentsByFile.set(file, text);
    headingsByFile.set(file, extractHeadings(text));
  }

  const errors = [];
  const normalizedRoot = resolve(rootDir);

  for (const file of files) {
    const relSource = normalizePosix(relative(normalizedRoot, file));
    const links = extractLinks(contentsByFile.get(file));
    for (const { line, target } of links) {
      if (!target || EXTERNAL_SCHEME.test(target) || target.startsWith('//')) continue;
      const hashIndex = target.indexOf('#');
      const rawPath = hashIndex === -1 ? target : target.slice(0, hashIndex);
      const rawFragment = hashIndex === -1 ? '' : target.slice(hashIndex + 1);
      const cleanPath = rawPath.split('?')[0];

      const decodedPath = safeDecode(cleanPath);
      if (decodedPath === null) {
        errors.push(`${relSource}:${line}: malformed percent-encoding in link "${target}"`);
        continue;
      }

      const targetFile = decodedPath
        ? decodedPath.startsWith('/')
          ? resolve(normalizedRoot, decodedPath.slice(1))
          : resolve(dirname(file), decodedPath)
        : file;

      const relTarget = normalizePosix(relative(normalizedRoot, targetFile));
      if (relTarget.startsWith('../') || relTarget === '..') {
        errors.push(`${relSource}:${line}: link escapes repository root: "${target}"`);
        continue;
      }

      if (!existsSync(targetFile)) {
        errors.push(`${relSource}:${line}: broken link target "${target}"`);
        continue;
      }

      if (!rawFragment) continue;
      const decodedFragment = safeDecode(rawFragment);
      if (decodedFragment === null) {
        errors.push(`${relSource}:${line}: malformed percent-encoding in anchor "${target}"`);
        continue;
      }

      if (statSync(targetFile).isFile() && extname(targetFile).toLowerCase() === '.md') {
        let headings = headingsByFile.get(targetFile);
        if (!headings) {
          headings = extractHeadings(readFileSync(targetFile, 'utf8'));
          headingsByFile.set(targetFile, headings);
        }
        const normalizedFragment = decodedFragment.toLowerCase();
        if (!headings.has(normalizedFragment)) {
          errors.push(
            `${relSource}:${line}: broken anchor "#${decodedFragment}" in "${relTarget}"`,
          );
        }
      }
    }
  }

  return { files, errors };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const { files, errors } = checkDocs(ROOT);
  if (errors.length) {
    for (const error of errors) console.error(error);
    process.exitCode = 1;
  } else {
    console.log(
      `Checked ${files.length} Markdown files: all internal links and anchors are valid.`,
    );
  }
}
