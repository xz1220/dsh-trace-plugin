import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import { apiError, errorMessage } from '../src/errors.js';

const result = await build({
  entryPoints: [fileURLToPath(new URL('../src/locale.js', import.meta.url))],
  bundle: true,
  write: false,
  format: 'esm',
  platform: 'browser',
});
const { translatorFor, supportedLocales } = await import(
  `data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`
);

test('one server error renders in the current locale with its recorded parameters', () => {
  const error = apiError({
    error: '录制格式版本 99 暂不支持，请更新 Codex Trace。',
    errorCode: 'unsupported_schema',
    errorParams: { version: 99 },
  });
  assert.ok(error instanceof Error);
  assert.equal(error.code, 'unsupported_schema');
  assert.deepEqual(error.params, { version: 99 });
  assert.equal(errorMessage(error, translatorFor('zh-CN')), '不支持此录制格式（版本 99）。');
  assert.equal(
    errorMessage(error, translatorFor('en-US')),
    'Unsupported recording format (version 99).',
  );
  assert.equal(errorMessage(error, translatorFor('zh-CN')), '不支持此录制格式（版本 99）。');
  assert.equal(error.message, '录制格式版本 99 暂不支持，请更新 Codex Trace。');
});

test('all supported host locales resolve coded errors with the documented English fallback', () => {
  const error = apiError({ errorCode: 'unsupported_schema', errorParams: { version: 7 } });
  for (const locale of supportedLocales) {
    const message = errorMessage(error, translatorFor(locale));
    assert.ok(message.includes('7'), `${locale}: missing schema version`);
    assert.ok(!message.includes('error.unsupported_schema'), `${locale}: untranslated error key`);
  }
  assert.equal(
    errorMessage(error, translatorFor('ja-JP')),
    'Unsupported recording format (version 7).',
  );
});

test('unknown error codes preserve the server text instead of displaying translation keys', () => {
  const error = apiError({
    error: 'A future server explains the exact failure.',
    errorCode: 'future_server_error',
  });
  assert.equal(errorMessage(error, translatorFor('en')), error.message);
  assert.equal(errorMessage(error, translatorFor('zh')), error.message);
});

test('legacy text errors and generic errors retain their original messages', () => {
  const translate = translatorFor('en');
  assert.equal(errorMessage('Legacy plain text', translate), 'Legacy plain text');
  assert.equal(errorMessage(new Error('Original exception'), translate), 'Original exception');
  assert.equal(
    errorMessage(apiError({ error: 'Legacy server text' }), translate),
    'Legacy server text',
  );
  assert.equal(
    errorMessage({ code: 'trace_error', message: 'Generic fallback' }, translate),
    'Generic fallback',
  );
  assert.equal(errorMessage(null, translate), '');
  assert.equal(errorMessage(undefined, translate), '');
});

test('API errors provide safe defaults when a transport has no structured body', () => {
  const missing = apiError(undefined);
  assert.equal(missing.message, 'Unable to read the recording.');
  assert.equal(missing.code, 'trace_error');
  assert.deepEqual(missing.params, {});
  assert.equal(apiError(null, 'Transport error text').message, 'Transport error text');
  assert.equal(apiError({ error: '' }, 'Text block fallback').message, 'Text block fallback');
});
