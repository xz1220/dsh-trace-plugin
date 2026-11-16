import { errorMessage, apiError } from './errors.js';
import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { createRoot } from 'react-dom/client';
import '../vendor/dsh/packages/client/ui-theme/src/styles/base.css';
import '../vendor/dsh/packages/client/ui-theme/src/styles/design-platform.css';
import '../vendor/dsh/packages/client/ui-theme/src/styles/focus.css';
import '../vendor/dsh/packages/client/ui-theme/src/styles/gradient-shadow-text.css';
import view from '../vendor/dsh/packages/client/ui-trajectory/src/client/views.module.css';
import './viewer.css';
import { createHost } from './host.js';
import { Failure, Skeleton } from './content.jsx';
import Trajectory from './Trajectory.jsx';
import { installIconSprite } from '../vendor/dsh/packages/client/ui-theme/src/client/icon-sprite.ts';
import { disposeImageTransfers } from './images.jsx';
import { LocaleContext } from './locale-context.jsx';
import { translatorFor, normalizeLocale } from './locale.js';
import { useChat } from './use-chat.js';

function App() {
  const host = useRef(),
    toastTimer = useRef();
  const [dark, setDark] = useState(false),
    [toast, setToast] = useState('');
  const [connected, setConnected] = useState(false);
  const [locale, setLocale] = useState('zh');
  const t = useMemo(() => translatorFor(locale), [locale]);
  const call = useCallback(
    (name, args = {}) =>
      host.current
        ? host.current.call(name, args)
        : Promise.reject(apiError({ errorCode: 'connecting' })),
    [],
  );
  const {
    data,
    loading,
    error,
    setError,
    setLoading,
    focusCallId,
    setFocusCallId,
    selectionInfo,
    received,
    invalidate,
    loadTrace,
    applyResult,
    earlier,
  } = useChat({ call, connected });
  const notify = useCallback((text) => {
    setToast(text);
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(''), 2200);
  }, []);
  const copy = useCallback(
    async (value) => {
      try {
        await navigator.clipboard.writeText(value);
        notify(t('codex.completeContentCopied'));
      } catch {
        notify(t('codex.copyFailedSelectTheTextToCopy'));
      }
    },
    [notify, t],
  );
  useEffect(() => {
    invalidate();
    let active = true;
    const apply = (value) => {
      if (active) applyResult(value);
    };
    const bridge = createHost({
      onResult: (result) => apply(result.structuredContent || result),
      onContext: (context) => {
        if (!active) return;
        if (context.theme) setDark(context.theme === 'dark');
        if (context.locale) setLocale(normalizeLocale(context.locale));
      },
      onError: (e) => {
        if (active) {
          setError(e);
          setLoading(false);
        }
      },
    });
    host.current = bridge;
    bridge
      .start()
      .then(async () => {
        if (bridge.preview) {
          const result = await bridge.call(
            'show_rollout_trace',
            bridge.preview.traceId ? { traceId: bridge.preview.traceId } : {},
          );
          apply(result);
        }
        if (!received.current) apply(await bridge.call('open_rollout_viewer'));
        if (active) setConnected(true);
      })
      .catch((e) => {
        if (active) {
          setError(e);
          setLoading(false);
        }
      });
    return () => {
      active = false;
      invalidate();
      bridge.dispose();
      clearTimeout(toastTimer.current);
    };
  }, [applyResult, invalidate, received, setError, setLoading]);
  useEffect(() => {
    document.body.toggleAttribute('data-ds-dark-theme', dark);
    document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
  }, [dark]);
  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);
  useEffect(() => {
    const notice = (event) => notify(errorMessage(event.detail, t));
    window.addEventListener('rollout-viewer:notice', notice);
    return () => window.removeEventListener('rollout-viewer:notice', notice);
  }, [notify, t]);
  useEffect(() => {
    const cleanup = [];
    installIconSprite({ effect: (setup) => cleanup.push(setup()), on: () => {} }, undefined);
    return () => cleanup.forEach((dispose) => dispose?.());
  }, []);
  useEffect(() => () => disposeImageTransfers(), []);
  return (
    <LocaleContext.Provider value={t}>
      <main className={`${view.root} app-frame`} aria-label="Codex Trace">
        {error && (
          <Failure
            error={error}
            retry={() =>
              data
                ? loadTrace(data.trace.id, null, { quiet: true, preserve: true })
                : location.reload()
            }
          />
        )}
        {data?.trace.issues?.map((issue, index) => (
          <Failure key={index} error={apiError({ error: issue.message, ...issue })} />
        ))}
        {loading ? (
          <Skeleton />
        ) : !data ? (
          <section className="app-empty" aria-live="polite">
            <h2>
              {selectionInfo?.unavailableReason
                ? t('codex.unableToReadThisChatTrajectory')
                : t('codex.noTrajectoryForThisChatYet')}
            </h2>
            <p>
              {selectionInfo?.unavailableReason
                ? errorMessage(selectionInfo.unavailableReason, t)
                : t('codex.newExecutionRecordsWillAppearAutomaticallyWhen')}
            </p>
          </section>
        ) : (
          <Trajectory
            key={`${data.trace.id}:${data.revision.split(':')[0]}:${data.projectionRevision || 0}`}
            {...{ data, call, earlier, copy, focusCallId }}
            onFocusApplied={() => setFocusCallId(null)}
          />
        )}
        <div className={`app-toast ${toast ? 'visible' : ''}`} role="status">
          {toast}
        </div>
      </main>
    </LocaleContext.Provider>
  );
}
createRoot(document.getElementById('root')).render(<App />);
