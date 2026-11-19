import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import {
  checkDocs,
  extractHeadings,
  extractLinks,
  slugifyHeading,
} from '../scripts/check-docs.mjs';

test('slugifyHeading matches GitHub heading anchors for English, punctuation, and CJK', () => {
  assert.equal(slugifyHeading('Quick start'), 'quick-start');
  assert.equal(slugifyHeading('rollout-local 来源冲突'), 'rollout-local-来源冲突');
  assert.equal(slugifyHeading('1. Install `dsh-trace-extension`'), '1-install-dsh-trace-extension');
  assert.equal(slugifyHeading('A & B'), 'a--b');
  assert.equal(slugifyHeading('[Linked](https://example.com) **Bold**'), 'linked-bold');
});

test('extractHeadings numbers duplicate headings and skips fenced code blocks', () => {
  const markdown = [
    '# Title',
    '## Section',
    '```md',
    '## Section',
    '# Fake',
    '```',
    '## Section',
    '<a id="custom-anchor"></a>',
  ].join('\n');
  const slugs = extractHeadings(markdown);
  assert.equal(slugs.has('title'), true);
  assert.equal(slugs.has('section'), true);
  assert.equal(slugs.has('section-1'), true);
  assert.equal(slugs.has('section-2'), false);
  assert.equal(slugs.has('fake'), false);
  assert.equal(slugs.has('custom-anchor'), true);
});

test('extractLinks handles inline links, reference defs, titles, and ignores code spans', () => {
  const markdown = [
    'See [one](docs/a.md#sec "Title"), ![img](<docs/pic (1).png>), and `[skip](missing.md)`.',
    '[ref]: docs/b.md#other',
    '~~~',
    '[fenced](ignored.md)',
    '~~~',
  ].join('\n');
  assert.deepEqual(extractLinks(markdown), [
    { line: 1, target: 'docs/a.md#sec' },
    { line: 1, target: 'docs/pic (1).png' },
    { line: 2, target: 'docs/b.md#other' },
  ]);
});

test('checkDocs validates valid links and catches missing files, broken anchors, escapes, and bad encoding', () => {
  const root = mkdtempSync(join(tmpdir(), 'dsh-docs-test-'));
  try {
    mkdirSync(join(root, 'docs'), { recursive: true });
    mkdirSync(join(root, 'node_modules', 'pkg'), { recursive: true });
    writeFileSync(join(root, 'node_modules', 'pkg', 'README.md'), '[bad](missing.md)\n', 'utf8');
    writeFileSync(
      join(root, 'docs', 'guide.md'),
      '# Guide\n\n## Repeat\n\n## Repeat\n\n## 中文标题\n',
      'utf8',
    );
    writeFileSync(
      join(root, 'README.md'),
      [
        '# Home',
        '[ok](docs/guide.md#repeat-1)',
        '[ok-cjk](docs/guide.md#中文标题)',
        '[ok-self](#home)',
        '[ok-ext](https://example.com/x#missing)',
        '[bad-file](docs/nope.md)',
        '[bad-anchor](docs/guide.md#nonexistent)',
        '[escape](../../outside.md)',
        '[bad-pct](docs/%E0%A4%A.md)',
        '[bad-anchor-pct](docs/guide.md#%E0%A4%A)',
      ].join('\n'),
      'utf8',
    );
    const { files, errors } = checkDocs(root);
    assert.equal(files.length, 2);
    assert.equal(errors.length, 5);
    assert.match(errors[0], /broken link target "docs\/nope\.md"/);
    assert.match(errors[1], /broken anchor "#nonexistent" in "docs\/guide\.md"/);
    assert.match(errors[2], /link escapes repository root/);
    assert.match(errors[3], /malformed percent-encoding in link/);
    assert.match(errors[4], /malformed percent-encoding in anchor/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
