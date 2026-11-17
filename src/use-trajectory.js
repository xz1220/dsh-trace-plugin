import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { readComplete } from './content.jsx';

// The keyed Trajectory view owns selection and folding. This hook owns the
// loaded records, their versions, and bounded detail reads for that view.
export function useTrajectoryData({ data, call, query, locale, reloadTrace }) {
  const traceId = data.trace.id;
  const [cells, setCells] = useState(new Map()),
    [requests, setRequests] = useState(new Map());
  const [loading, setLoading] = useState(true),
    [error, setError] = useState(''),
    [retryCount, setRetryCount] = useState(0);
  const [matches, setMatches] = useState(null),
    [searchBusy, setSearchBusy] = useState(false);
  const currentCells = useRef(cells),
    currentRequests = useRef(requests);
  currentCells.current = cells;
  currentRequests.current = requests;
  const versions = useRef(new Map()),
    inflight = useRef(new Map()),
    requestInflight = useRef(new Set()),
    live = useRef(true);
  const templates = useRef(new Map()),
    hydrated = useRef(new Map()),
    activeRecord = useRef(null);
  const api = useCallback((name, args) => call(name, { traceId, ...args }), [traceId, call]);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);
  useEffect(() => {
    let active = true;
    const changed = data.rows
      .filter((row) => versions.current.get(row.id) !== row.version)
      .map((row) => row.id);
    if (!changed.length) {
      setLoading(false);
      return;
    }
    async function refresh() {
      try {
        for (let offset = 0; offset < changed.length; offset += 200) {
          const page = await api('get_rollout_projection', {
            rowIds: changed.slice(offset, offset + 200),
          });
          if (!active) return;
          if (page.resync) {
            await reloadTrace(traceId, null, { quiet: true, preserve: true });
            return;
          }
          const replaced = new Set(page.rowIds);
          setCells((current) => {
            const next = new Map([...current].filter(([, cell]) => !replaced.has(cell.rowId)));
            for (const cell of page.cells) {
              templates.current.set(cell.recordId, cell);
              const old = current.get(cell.recordId);
              next.set(
                cell.recordId,
                old?.version === cell.version && !old.detailsPending ? old : cell,
              );
            }
            return next;
          });
          setRequests((current) => {
            const next = new Map(current);
            for (const request of page.requestNumbers)
              next.set(request.rowId, { ...request, detailsPending: true });
            return next;
          });
          for (const row of data.rows)
            if (replaced.has(row.id)) versions.current.set(row.id, row.version);
        }
        setError('');
      } catch (e) {
        if (active) setError(e);
      } finally {
        if (active) setLoading(false);
      }
    }
    refresh();
    return () => {
      active = false;
    };
  }, [api, data.rows, retryCount, reloadTrace, traceId]);

  const hydrate = useCallback(
    async (selected, force = false) => {
      const cell = currentCells.current.get(selected?.recordId) || selected;
      if (!cell || (!force && (!cell.detailsPending || cell.detailsError))) return;
      const key = `${cell.recordId}:${cell.version}`;
      if (inflight.current.has(key)) return inflight.current.get(key);
      const promise = (async () => {
        try {
          const metadata = await api('get_rollout_cell_detail', {
            rowId: cell.rowId,
            cellKey: cell.cellKey,
          });
          const fields = await Promise.all(
            Object.entries(metadata.fields).map(async ([field, info]) => {
              const text = await readComplete(
                api,
                'read_rollout_cell_text',
                {
                  rowId: cell.rowId,
                  cellKey: cell.cellKey,
                  field,
                  version: metadata.cell.version,
                  snapshot: metadata.snapshot,
                },
                () => live.current,
              );
              return [field, info.json && text !== null ? JSON.parse(text) : text];
            }),
          );
          if (!live.current) return;
          const complete = {
            ...metadata.cell,
            ...Object.fromEntries(fields),
            detailsPending: false,
          };
          const size = Object.values(metadata.fields).reduce(
            (sum, field) => sum + field.totalChars * 4,
            0,
          );
          setCells((current) => {
            if (current.get(cell.recordId)?.version !== cell.version) return current;
            const next = new Map(current);
            next.set(cell.recordId, complete);
            hydrated.current.delete(cell.recordId);
            hydrated.current.set(cell.recordId, size);
            let total = [...hydrated.current.values()].reduce((sum, value) => sum + value, 0);
            for (const [id, bytes] of hydrated.current) {
              if (hydrated.current.size <= 20 && total <= 16 * 1024 * 1024) break;
              if (id === activeRecord.current || id === cell.recordId) continue;
              hydrated.current.delete(id);
              total -= bytes;
              if (templates.current.has(id)) next.set(id, templates.current.get(id));
            }
            return next;
          });
        } catch (e) {
          if (live.current)
            setCells((current) => {
              if (current.get(cell.recordId)?.version !== cell.version) return current;
              const next = new Map(current);
              next.set(cell.recordId, { ...cell, detailsError: e });
              return next;
            });
        } finally {
          inflight.current.delete(key);
        }
      })();
      inflight.current.set(key, promise);
      return promise;
    },
    [api],
  );
  const selectRequest = useCallback(
    (selected, force = false) => {
      const request = currentRequests.current.get(selected?.rowId) || selected;
      const key = `${request?.rowId}:${request?.version}`;
      if (
        !request?.detailsPending ||
        (!force && request.detailsError) ||
        requestInflight.current.has(key)
      )
        return;
      requestInflight.current.add(key);
      api('get_rollout_request_info', { rowId: request.rowId })
        .then((value) => {
          if (live.current)
            setRequests((current) => {
              if (current.get(request.rowId)?.version !== request.version) return current;
              const next = new Map(current);
              next.set(request.rowId, { ...value.request, detailsPending: false });
              return next;
            });
        })
        .catch((e) => {
          if (live.current)
            setRequests((current) => {
              if (current.get(request.rowId)?.version !== request.version) return current;
              const next = new Map(current);
              next.set(request.rowId, { ...request, detailsError: e });
              return next;
            });
        })
        .finally(() => requestInflight.current.delete(key));
    },
    [api],
  );

  const selectCell = useCallback(
    (cell) => {
      activeRecord.current = cell?.recordId ?? null;
      return hydrate(cell);
    },
    [hydrate],
  );
  // Hydrating a body does not change which execution records are loaded.
  const rowIds = useMemo(() => data.rows.map((row) => row.id), [data.rows]);
  useEffect(() => {
    if (!query.trim()) {
      setMatches(null);
      setSearchBusy(false);
      return;
    }
    let active = true;
    setSearchBusy(true);
    const timer = setTimeout(async () => {
      try {
        const found = [];
        for (let offset = 0; offset < rowIds.length; offset += 200) {
          const result = await api('search_rollout_cells', {
            query,
            rowIds: rowIds.slice(offset, offset + 200),
            locale,
          });
          if (!active) return;
          found.push(...result.matches);
        }
        if (active) {
          setMatches(new Set(found));
          setError('');
        }
      } catch (e) {
        if (active) setError(e);
      } finally {
        if (active) setSearchBusy(false);
      }
    }, 200);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [api, query, rowIds, data.revision, retryCount, locale]);
  const watchToolResult = useCallback(
    (seq, receive) => {
      let active = true;
      const row = data.rows.find((value) => value.seq === seq);
      if (row)
        readComplete(
          api,
          'read_rollout_text',
          { rowId: row.id, section: 'raw_result' },
          () => active,
        )
          .then((text) => {
            if (!active) return;
            if (text === null) {
              receive(undefined);
              return;
            }
            try {
              receive(JSON.parse(text));
            } catch {
              receive(text);
            }
          })
          .catch(() => {
            if (active) receive(undefined);
          });
      return () => {
        active = false;
        receive(undefined);
      };
    },
    [api, data.rows],
  );
  const retry = useCallback(() => setRetryCount((value) => value + 1), []);
  return {
    cells,
    requests,
    loading,
    error,
    retry,
    hydrate,
    selectCell,
    selectRequest,
    matches,
    searchBusy,
    watchToolResult,
  };
}
