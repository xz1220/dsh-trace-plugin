import { readFile } from 'node:fs/promises';

const { version } = JSON.parse(await readFile('package.json', 'utf8'));
const changelog = await readFile('CHANGELOG.md', 'utf8');
const escaped = version.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const heading = new RegExp(`^## (?:\\[${escaped}\\](?:\\([^\\n]*\\))?|${escaped})(?:\\s|$)`, 'm');
const match = heading.exec(changelog);
if (!match) throw new Error(`CHANGELOG.md has no release entry for ${version}.`);
const start = match.index;
const rest = changelog.slice(start);
const next = /^## /gm;
next.lastIndex = match[0].length;
const end = next.exec(rest)?.index ?? rest.length;
process.stdout.write(rest.slice(0, end).trim() + '\n');
