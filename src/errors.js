export function apiError(value, fallback = 'Unable to read the recording.') {
  const error = new Error(value?.error || fallback);
  error.code = value?.errorCode || 'trace_error';
  error.params = value?.errorParams || {};
  return error;
}

export function errorMessage(error, translate) {
  const code = error?.code;
  if (code && code !== 'trace_error') {
    const key = `error.${code}`;
    const message = translate(key, error.params);
    if (message !== key) return message;
  }
  return error?.message || String(error || '');
}
