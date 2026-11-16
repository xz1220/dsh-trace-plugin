import { useState, useRef, useCallback, useEffect } from 'react';
import { apiError } from './errors.js';

// Own chat selection, paging and live revisions in one place.
export function useChat({ call, connected }) {
  const received = useRef(false),
    generation = useRef(0),
    earlierBusy = useRef(false),
    latestData = useRef(null);
  const [data, setData] = useState(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState('');
  const [focusCallId, setFocusCallId] = useState(null);
  const [selectionInfo, setSelectionInfo] = useState(null);
  latestData.current = data;
  const invalidate = useCallback(() => {
    generation.current += 1;
  }, []);
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
  }, [connected, loading, data?.trace.id, call, loadTrace, applyResult]);
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
  return {
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
  };
}
