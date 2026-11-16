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

function App() {
  const host = useRef(),
    received = useRef(false),
    generation = useRef(0),
    earlierBusy = useRef(false),
    toastTimer = useRef();
  const [data, setData] = useState(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState('');
  const [dark, setDark] = useState(false),
    [toast, setToast] = useState('');
  const [focusCallId, setFocusCallId] = useState(null);
  const [selectionInfo, setSelectionInfo] = useState(null);
  const [followingThread, setFollowingThread] = useState(null),
    [connected, setConnected] = useState(false);
  const latestData = useRef(null);
  latestData.current = data;
  const [locale, setLocale] = useState('zh');
  const t = useMemo(() => translatorFor(locale), [locale]);
  const call = useCallback(
    (name, args = {}) =>
      host.current
        ? host.current.call(name, args)
        : Promise.reject(apiError({ errorCode: 'connecting' })),
    [],
  );
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
  const loadTrace = useCallback(
    async (id, focus = null, { quiet = false, preserve = false } = {}) => {
      if (!id) return;
      const ticket = ++generation.current;
      if (!quiet) setLoading(true);
      setError('');
      try {
        let value = await call('get_rollout_overview', { traceId: id });
        if (focus) {
          const { row } = await call('get_rollout_record', { traceId: id, callId: focus });
          focus = row.callId;
          while (value.hasEarlier && value.beforeSeq > row.seq) {
            if (ticket !== generation.current) return;
            const page = await call('get_rollout_overview', {
              traceId: id,
              beforeSeq: value.beforeSeq,
              limit: 200,
            });
            if (!page.rows.length || page.beforeSeq >= value.beforeSeq)
              throw apiError({ errorCode: 'history_paging_stalled' });
            const rows = new Map(
              [...page.rows, ...value.rows].map((record) => [record.id, record]),
            );
            value = {
              ...value,
              rows: [...rows.values()].sort((a, b) => a.seq - b.seq),
              beforeSeq: page.beforeSeq,
              hasEarlier: page.hasEarlier,
            };
          }
        }
        if (ticket !== generation.current) return;
        setData(value);
        if (!preserve) setFocusCallId(focus);
        setLoading(false);
      } catch (e) {
        if (ticket === generation.current) {
          setError(e);
          setLoading(false);
        }
      }
    },
    [call],
  );
  const applyResult = useCallback(
    (value) => {
      if (!value || !['open', 'trace', 'select'].includes(value.view)) return;
      received.current = true;
      setFollowingThread(value.currentThreadId || null);
      if (value.view === 'open') {
        if (value.currentThreadId) setSelectionInfo({ currentThreadId: value.currentThreadId });
        loadTrace(value.trace.id, value.focusCallId || null);
        return;
      }
      if (value.view === 'trace' && Array.isArray(value.rows)) {
        setSelectionInfo(value.currentThreadId ? { currentThreadId: value.currentThreadId } : null);
        // A delayed host snapshot may predate the data already loaded by this UI connection.
        if (latestData.current?.trace.id === value.trace.id) {
          loadTrace(value.trace.id, null, { quiet: true, preserve: true });
          return;
        }
        generation.current += 1;
        setData(value);
        setFocusCallId(null);
        setLoading(false);
        setError('');
        return;
      }
      if (value.view === 'select') {
        generation.current += 1;
        setSelectionInfo({
          currentThreadId: value.currentThreadId,
          unavailableReason: value.unavailableReason
            ? apiError({
                error: value.unavailableReason,
                errorCode: value.errorCode,
                errorParams: value.errorParams,
              })
            : null,
        });
        setData(null);
        setFocusCallId(null);
        setLoading(false);
        setError('');
      }
    },
    [loadTrace],
  );
  useEffect(() => {
    generation.current += 1;
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
      generation.current += 1;
      bridge.dispose();
      clearTimeout(toastTimer.current);
    };
  }, [applyResult]);
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
  useEffect(() => {
    if (!connected || loading) return;
    let cancelled = false,
      busy = false;
    async function poll() {
      if (busy || document.hidden) return;
      busy = true;
      const current = latestData.current,
        ticket = generation.current;
      const stale = () => cancelled || ticket !== generation.current;
      try {
        if (!current) {
          const result = await call('open_rollout_viewer');
          if (!stale()) applyResult(result);
          return;
        }
        const traceId = current.trace.id;
        if (followingThread) {
          const resolved = await call('get_rollout_binding', { threadId: followingThread });
          if (stale()) return;
          const match = resolved.currentThreadId === followingThread ? resolved.trace : null;
          if (match && match.id !== traceId) {
            await loadTrace(match.id, null, { quiet: true });
            return;
          }
        }
        const delta = await call('get_rollout_delta', { traceId, revision: current.revision });
        if (stale()) return;
        setError('');
        if (delta.resync) {
          await loadTrace(traceId, null, { quiet: true, preserve: true });
          return;
        }
        if (!delta.unchanged)
          setData((current) => {
            if (current?.trace.id !== traceId) return current;
            const rows = new Map(current.rows.map((row) => [row.id, row]));
            for (const row of delta.rows) rows.set(row.id, row);
            return { ...current, ...delta, rows: [...rows.values()].sort((a, b) => a.seq - b.seq) };
          });
      } catch (e) {
        if (!stale()) setError(e);
      } finally {
        busy = false;
      }
    }
    const timer = setInterval(poll, 1500);
    document.addEventListener('visibilitychange', poll);
    poll();
    return () => {
      cancelled = true;
      clearInterval(timer);
      document.removeEventListener('visibilitychange', poll);
    };
  }, [connected, loading, data?.trace.id, followingThread, call, loadTrace, applyResult]);
  const earlier = useCallback(async () => {
    if (!data?.hasEarlier || earlierBusy.current) return false;
    earlierBusy.current = true;
    const ticket = generation.current;
    try {
      const page = await call('get_rollout_overview', {
        traceId: data.trace.id,
        beforeSeq: data.beforeSeq,
        limit: 200,
      });
      if (ticket !== generation.current) return false;
      setData((current) => {
        if (current?.trace.id !== data.trace.id) return current;
        const rows = new Map(current.rows.map((row) => [row.id, row]));
        for (const row of page.rows) rows.set(row.id, row);
        return {
          ...current,
          rows: [...rows.values()].sort((a, b) => a.seq - b.seq),
          hasEarlier: page.hasEarlier,
          beforeSeq: page.beforeSeq,
        };
      });
      return page.rows.length > 0;
    } catch (e) {
      if (ticket === generation.current) setError(e);
      return false;
    } finally {
      earlierBusy.current = false;
    }
  }, [data, call]);
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
            thread="all"
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
