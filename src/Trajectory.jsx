import React, { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import { TrajectoryTable } from '../vendor/dsh/packages/client/ui-trajectory/src/client/TrajectoryTable.tsx';
import { TrajectoryTimeline } from '../vendor/dsh/packages/client/ui-trajectory/src/client/TrajectoryTimeline.tsx';
import { TrajectoryToolbar } from '../vendor/dsh/packages/client/ui-trajectory/src/client/TrajectoryToolbar.tsx';
import { trajectoryTimelineFocusIndexes } from '../vendor/dsh/packages/client/ui-trajectory/src/client/timeline.ts';
import { useTranslation } from './locale-context.jsx';
import { renderImageSlot as renderSlot, loadImage } from './images.jsx';
import { Failure, Skeleton, RequestContent, compactionText } from './content.jsx';
import view from '../vendor/dsh/packages/client/ui-trajectory/src/client/views.module.css';
import { durationPreference, wrappingPreference } from './preferences.js';
import { trajectoryTurns, trajectoryTiming } from './trajectory-order.js';
import { useTrajectoryData } from './use-trajectory.js';

const toggle = (set, key) =>
  set((current) => {
    const next = new Set(current);
    next.has(key) ? next.delete(key) : next.add(key);
    return next;
  });
const toggleAll = (set, ids, collapsed) =>
  set((current) => {
    const next = new Set(current);
    for (const id of ids) collapsed ? next.delete(id) : next.add(id);
    return next;
  });

export default function Trajectory({
  data,
  call,
  earlier,
  copy,
  focusCallId,
  onFocusApplied,
  reloadTrace,
}) {
  const t = useTranslation();
  const groupOf = useCallback(
    (cell) =>
      cell.inputHistory
        ? t('codex.historyInRequest')
        : cell.cellKey === 'compaction' || cell.purpose === 'compaction'
          ? t('group.compaction', { seq: cell.seq })
          : cell.step > 0
            ? t('group.step', { step: cell.step })
            : cell.group,
    [t],
  );
  const captionOf = useCallback(
    (cell) => {
      if (cell.kind === 'system' && cell.cellKey === 'prompt')
        return t(cell.previousPromptDetail ? 'codex.instructionsUpdated' : 'codex.instructions');
      if (cell.kind === 'compacted')
        return cell.compactionApplied
          ? t('codex.contextCompactionApplied')
          : t('codex.contextCompaction');
      if (cell.kind === 'message' && cell.text === '（仅工具调用）')
        return `（${t('layout.toolCallOnly')}）`;
      if (['user', 'context', 'message'].includes(cell.kind) && /^(图片|文件) ×/.test(cell.text)) {
        const images = cell.sourceBlocks?.filter((block) => block.attachment).length ?? 0,
          files = cell.sourceBlocks?.filter((block) => block.file).length ?? 0;
        return [
          images ? t('layout.imageCount', { count: images }) : '',
          files ? t('layout.fileAttachments', { count: files }) : '',
        ]
          .filter(Boolean)
          .join(' · ');
      }
      return cell.text;
    },
    [t],
  );
  const traceId = data.trace.id;
  const [collapsedTurns, setCollapsedTurns] = useState(new Set()),
    [collapsedAssistants, setCollapsedAssistants] = useState(new Set()),
    [collapsedTools, setCollapsedTools] = useState(new Set());
  const duration = useSyncExternalStore(
    durationPreference.subscribe,
    durationPreference.getSnapshot,
  );
  const [actualTime, setActualTime] = useState(false);
  const [query, setQuery] = useState('');
  const {
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
  } = useTrajectoryData({ data, call, query, locale: t.locale, reloadTrace });
  const [range, setRange] = useState(null),
    [selectedIndex, setSelectedIndex] = useState(null);
  useEffect(() => {
    setRange(null);
  }, [duration, actualTime]);
  const [selection, setSelection] = useState(null),
    [focus, setFocus] = useState(null);
  const wrapped = useSyncExternalStore(
    wrappingPreference.subscribe,
    wrappingPreference.getSnapshot,
  );
  const visibleCells = useMemo(
    () =>
      [...cells.values()]
        .sort((a, b) => a.seq - b.seq || a.slot - b.slot)
        .map((cell, index) => ({
          ...trajectoryTiming(cell),
          ...(cell.compactionInfo ? { outputDetail: compactionText(cell.compactionInfo, t) } : {}),
          index: index + 1,
          group: groupOf(cell),
          text: captionOf(cell),
        })),
    [cells, t, groupOf, captionOf],
  );
  const turns = useMemo(() => trajectoryTurns(visibleCells), [visibleCells]);
  const requestNumbers = useMemo(() => {
    const visible = new Set(visibleCells.map((cell) => cell.rowId));
    return [...requests.values()]
      .filter((request) => visible.has(request.rowId))
      .sort((a, b) => a.seq - b.seq)
      .map((request) => ({ ...trajectoryTiming(request), group: groupOf(request) }));
  }, [requests, visibleCells, groupOf]);

  const selectIndex = useCallback(
    (index) => {
      setSelectedIndex(index);
      const cell = visibleCells.find((value) => value.index === index);
      selectCell(cell);
    },
    [visibleCells, selectCell],
  );
  const searchIndexes = useMemo(
    () =>
      matches === null
        ? null
        : new Set(
            visibleCells.filter((cell) => matches.has(cell.recordId)).map((cell) => cell.index),
          ),
    [visibleCells, matches],
  );
  const mode = duration ? (actualTime ? 'actual' : 'duration') : actualTime ? 'time' : 'sequence';
  const timelineFocus = useMemo(
    () => (range === null ? null : trajectoryTimelineFocusIndexes(turns, range, mode)),
    [turns, range, mode],
  );
  const turnIds = turns
    .filter(
      (turn) =>
        turn.turn !== null &&
        turn.groups
          .flatMap((group) => group.cells)
          .filter((cell) => cell.kind !== 'system' && !cell.requestOnly).length > 1,
    )
    .map((turn) => turn.turn);
  const assistantIds = visibleCells
    .filter(
      (cell, index) =>
        cell.kind === 'message' && ['tool', 'subtool'].includes(visibleCells[index + 1]?.kind),
    )
    .map((cell) => cell.recordId);
  const toolIds = visibleCells
    .filter((cell, index) => cell.kind === 'tool' && visibleCells[index + 1]?.kind === 'subtool')
    .map((cell) => cell.recordId);
  const allTurns = turnIds.length > 0 && turnIds.every((id) => collapsedTurns.has(id));
  const allAssistants =
    assistantIds.length > 0 && assistantIds.every((id) => collapsedAssistants.has(id));
  const allTools = toolIds.length > 0 && toolIds.every((id) => collapsedTools.has(id));
  const wrapping = useMemo(
    () => ({
      getDefault: () => wrapped,
      setDefault: wrappingPreference.set,
      label: t('record.wrapLines'),
    }),
    [wrapped, t],
  );
  const requestContent = useCallback(
    (request, tab) => (
      <RequestContent
        key={`${request.rowId}:${request.version}:${tab}`}
        {...{ traceId, request, tab, call, copy }}
      />
    ),
    [traceId, call, copy],
  );
  const renderPending = useCallback(
    (record) =>
      record.detailsError ? (
        <Failure
          error={record.detailsError}
          retry={() => (record.recordId ? hydrate(record, true) : selectRequest(record, true))}
        />
      ) : (
        <Skeleton />
      ),
    [hydrate, selectRequest],
  );

  if (loading) return <Skeleton />;
  return (
    <>
      {error && <Failure error={error} retry={retry} />}
      <TrajectoryToolbar
        actualDuration={duration}
        onActualDurationChange={(value) => {
          setRange(null);
          durationPreference.set(value);
        }}
        actualTime={actualTime}
        onActualTimeChange={(value) => {
          setRange(null);
          setActualTime(value);
        }}
        allTurnsCollapsed={allTurns}
        onToggleAllTurns={() => toggleAll(setCollapsedTurns, turnIds, allTurns)}
        allAssistantsCollapsed={allAssistants}
        onToggleAllAssistants={() => toggleAll(setCollapsedAssistants, assistantIds, allAssistants)}
        allSubCallsCollapsed={allTools}
        showSubCalls={toolIds.length > 0}
        onToggleAllSubCalls={() => toggleAll(setCollapsedTools, toolIds, allTools)}
        searchQuery={query}
        onSearchQueryChange={setQuery}
        t={t}
      />
      <TrajectoryTimeline
        turns={turns}
        mode={mode}
        range={range}
        onRangeChange={setRange}
        hasEarlierRecords={data.hasEarlier}
        onLoadEarlier={earlier}
        selectedIndex={selectedIndex}
        searchMatchIndexes={searchIndexes}
        onRecordSelect={(index) => {
          setRange(null);
          setSelection({ index });
        }}
        onRecordFocus={(index) => setFocus({ index })}
        t={t}
      />
      {query && (
        <div className="app-search-status" role="status">
          {searchBusy
            ? t('codex.searchingTheFullContentOfLoadedRecords')
            : t('codex.matchesInLoadedRecords', { value1: matches?.size || 0 })}
        </div>
      )}
      <div className={`${view.ledger} app-ledger-region`}>
        <TrajectoryTable
          turns={turns}
          requestNumbers={requestNumbers}
          t={t}
          renderSlot={renderSlot}
          loadImage={loadImage}
          watchToolResult={watchToolResult}
          inspectCallId={focusCallId}
          onInspectApplied={onFocusApplied}
          stringWrapping={wrapping}
          collapsedTurns={collapsedTurns}
          onToggleTurn={(id) => toggle(setCollapsedTurns, id)}
          collapsedAssistants={collapsedAssistants}
          onToggleAssistant={(id) => toggle(setCollapsedAssistants, id)}
          collapsedTools={collapsedTools}
          onToggleTool={(id) => toggle(setCollapsedTools, id)}
          timelineFocusIndexes={timelineFocus}
          searchMatchIndexes={searchIndexes}
          onSelectedIndexChange={selectIndex}
          onRecordSelect={(index) => {
            if (timelineFocus && !timelineFocus.has(index)) setRange(null);
          }}
          recordSelection={selection}
          recordFocus={focus}
          hasOlderRecords={data.hasEarlier}
          onLoadOlder={earlier}
          historyStartSeq={data.rows[0]?.seq}
          onClearSelection={() => {
            setRange(null);
            setSelection(null);
            setFocus(null);
          }}
          onRequestSelected={selectRequest}
          renderRequestContent={requestContent}
          renderPending={renderPending}
        />
      </div>
    </>
  );
}
