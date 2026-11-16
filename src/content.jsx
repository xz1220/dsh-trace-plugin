import { apiError } from './errors.js';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  IconCopyOutlineRegular,
  IconChevronRightOutlineRegular,
  JsonTree,
  MarkdownText,
} from '../vendor/dsh/primitives.ts';
import table from '../vendor/dsh/packages/client/ui-trajectory/src/client/TrajectoryTable.module.css';
import { useTranslation } from './locale-context.jsx';
import { errorMessage } from './errors.js';

export function Failure({ error, retry }) {
  const t = useTranslation();
  return (
    <div className="app-error" role="alert">
      <strong>{t('codex.unableToRead')}</strong>
      <p>{errorMessage(error, t)}</p>
      {retry && (
        <button type="button" className="app-link" onClick={retry}>
          {t('retry')}
        </button>
      )}
    </div>
  );
}
export function Skeleton() {
  const t = useTranslation();
  return (
    <div className="app-skeleton" role="status" aria-label={t('codex.loadingContent')}>
      <i />
      <i />
      <i />
    </div>
  );
}

export function compactionText(info, t) {
  const lines = [
    info?.applied
      ? t('codex.theCompactedContextWasAppliedToSubsequent')
      : t('codex.theCompactionRequestWasRecordedApplicationTo'),
  ];
  const roles = {
    user: t('codex.user'),
    assistant: t('codex.assistant'),
    developer: t('codex.developer'),
    system: t('codex.system'),
  };
  for (const [field, label] of [
    ['before', t('codex.beforeCompaction')],
    ['after', t('codex.afterCompaction')],
  ]) {
    const value = info?.[field];
    if (value)
      lines.push(
        `${label}：${value.items} ${t('codex.items')}${
          Object.keys(value.roles || {}).length
            ? ` (${Object.entries(value.roles)
                .map(([role, count]) => `${roles[role] || role} ${count}`)
                .join(' · ')})`
            : ''
        }`,
      );
  }
  lines.push(t('codex.theTimelineKeepsRecordedReadableMessagesSubsequent'));
  if (info?.after?.encryptedItems || info?.output?.encryptedItems)
    lines.push(t('codex.theCompactedContextContainsOpaqueEncryptedItems'));
  if (info?.readableSummary)
    lines.push(
      `${t('codex.recordedReadableSummary')}：\n\n${info.readableSummary}${info.readableSummaryTruncated ? `\n\n${t('codex.summaryPreviewTruncatedSeeTheRawResponse')}` : ''}`,
    );
  return lines.join('\n\n');
}
export async function readComplete(api, name, arguments_, isCurrent = () => true) {
  let text = '',
    offset = 0;
  while (offset !== null) {
    if (!isCurrent()) throw apiError({ errorCode: 'cancelled' });
    const result = await api(name, { ...arguments_, offset });
    if (result.available === false) return null;
    text += result.text;
    if (result.nextOffset !== null && result.nextOffset <= offset)
      throw apiError({ errorCode: 'paging_stalled' });
    offset = result.nextOffset;
  }
  return text;
}

export function TextContent({ rowId, section, itemIndex, api, copy, label }) {
  const t = useTranslation();
  const labels = {
    copyValue: t('copy.value'),
    copyJson: t('copy.json'),
    copyPath: t('copy.path'),
    copyPrettyJson: t('copy.prettyJson'),
    copyCompactJson: t('copy.compactJson'),
    copied: t('copied'),
    copyFailed: t('copy.failed'),
    collapseNode: t('collapse'),
    expandNode: t('expand'),
    copyButtonTitle: (action) => t('copy.optionsHint', { action }),
  };
  const [data, setData] = useState(null),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false);
  const [wrap, setWrap] = useState(true),
    [tree, setTree] = useState(true);
  const ticket = useRef(0),
    dataRef = useRef(null);
  const load = useCallback(
    async (offset = 0) => {
      const id = ++ticket.current;
      setBusy(true);
      setError('');
      try {
        const value = await api('read_rollout_text', {
          rowId,
          section,
          ...(itemIndex !== undefined ? { itemIndex } : {}),
          offset,
        });
        if (id !== ticket.current) return;
        const next = {
          ...value,
          text: offset ? (dataRef.current?.text || '') + value.text : value.text,
        };
        dataRef.current = next;
        setData(next);
      } catch (e) {
        if (id === ticket.current) setError(e);
      } finally {
        if (id === ticket.current) setBusy(false);
      }
    },
    [api, rowId, section, itemIndex],
  );
  useEffect(() => {
    ticket.current += 1;
    setData(null);
    dataRef.current = null;
    setError('');
    load();
    return () => {
      ticket.current += 1;
    };
  }, [load]);
  async function copyAll() {
    const id = ticket.current;
    setBusy(true);
    setError('');
    try {
      const text = await readComplete(
        api,
        'read_rollout_text',
        { rowId, section, ...(itemIndex !== undefined ? { itemIndex } : {}) },
        () => ticket.current === id,
      );
      if (text !== null) await copy(text);
    } catch (e) {
      if (ticket.current === id) setError(e);
    } finally {
      if (ticket.current === id) setBusy(false);
    }
  }
  let json;
  if (data?.available && data.nextOffset === null && data.text.length < 250000) {
    try {
      json = JSON.parse(data.text);
    } catch {}
  }
  return (
    <section className="app-text" aria-label={label}>
      <div className="app-content-toolbar">
        <span>
          {label}
          {data && ` · ${data.totalChars.toLocaleString()} ${t('codex.characters')}`}
        </span>
        <div>
          {json !== undefined && (
            <button
              type="button"
              className="app-button"
              aria-pressed={tree}
              onClick={() => setTree(!tree)}
            >
              {tree ? t('codex.raw') : t('codex.tree')}
            </button>
          )}
          <button
            type="button"
            className="app-button"
            aria-pressed={wrap}
            onClick={() => setWrap(!wrap)}
          >
            {t('codex.wrap')}
          </button>
          <button
            type="button"
            className="app-icon"
            disabled={busy || data?.available === false}
            aria-label={t('codex.copyComplete', { value1: label })}
            title={t('codex.copyComplete', { value1: label })}
            onClick={copyAll}
          >
            <IconCopyOutlineRegular size={14} />
          </button>
        </div>
      </div>
      {error && <Failure error={error} retry={() => load(data?.nextOffset || 0)} />}
      {!data && !error ? (
        <Skeleton />
      ) : data?.available === false ? (
        <p className={table.noPayload}>{t('codex.thisContentIsNotInTheRecording')}</p>
      ) : json !== undefined && tree ? (
        <JsonTree
          data={json}
          label={label}
          labels={labels}
          collapsedStringLines={12}
          className={table.jsonPayload}
        />
      ) : (
        <pre className={`${table.payload} app-raw`} data-wrap={wrap}>
          {data?.text}
        </pre>
      )}
      {data?.nextOffset !== null && data?.nextOffset !== undefined && (
        <button className="app-load-more" disabled={busy} onClick={() => load(data.nextOffset)}>
          {busy
            ? t('codex.loading')
            : t('codex.loadMoreCharacters', {
                value1: data.nextOffset.toLocaleString(),
                value2: data.totalChars.toLocaleString(),
              })}
        </button>
      )}
    </section>
  );
}

function PromptContext({ request, detail, api, copy }) {
  const t = useTranslation();
  const [mode, setMode] = useState('full'),
    [role, setRole] = useState('all'),
    [expanded, setExpanded] = useState(null);
  const [copying, setCopying] = useState(false),
    [error, setError] = useState('');
  const { context, messages } = detail;
  // Even when a prefix is missing, preserve the known inherited items.
  const current = messages.filter((message) => mode === 'full' || !message.inherited);
  const visible = current.filter((message) => role === 'all' || message.role === role);
  const opened =
    expanded === null
      ? visible.find((message) => message.type !== 'additional_tools')?.index
      : expanded;
  async function copyContext() {
    setCopying(true);
    setError('');
    try {
      const text = await readComplete(api, 'read_rollout_text', {
        rowId: request.rowId,
        section: 'full_context',
      });
      await copy(text || '');
    } catch (e) {
      setError(e);
    } finally {
      setCopying(false);
    }
  }
  return (
    <>
      <div className="app-context-note" data-incomplete={!context.complete || undefined}>
        <strong>
          {!context.complete
            ? t('codex.earlierRecordingMissingShowingKnownContext')
            : context.incremental
              ? t('codex.completeContextRestoredAlongTheResponseChain')
              : t('codex.recordedClientRequestInput')}
        </strong>
        <span>
          {context.incremental
            ? t('codex.inheritedInputPreviousOutputAndCurrentIncrement')
            : t('codex.originalRolesAndInputOrderArePreserved')}
        </span>
        {messages.some((message) => message.type === 'compaction') && (
          <span>{t('codex.thisRequestUsesACompactedContextSnapshot')}</span>
        )}
      </div>
      <div className="app-prompt-controls">
        <div role="group" aria-label={t('codex.contextScope')}>
          <button
            type="button"
            className="app-button"
            aria-pressed={mode === 'full'}
            onClick={() => setMode('full')}
          >
            {context.complete ? t('codex.prompt') : t('codex.knownContext')} {messages.length}
          </button>
          {context.incremental && (
            <button
              type="button"
              className="app-button"
              aria-pressed={mode === 'delta'}
              onClick={() => setMode('delta')}
            >
              {t('codex.currentIncrement')} {messages.filter((m) => !m.inherited).length}
            </button>
          )}
        </div>
        <button
          type="button"
          className="app-icon"
          disabled={copying}
          aria-label={
            context.complete ? t('codex.copyCompleteContext') : t('codex.copyKnownContext')
          }
          onClick={copyContext}
        >
          <IconCopyOutlineRegular size={14} />
        </button>
      </div>
      <div className="app-prompt-filter">
        <select
          aria-label={t('codex.filterInputRoles')}
          value={role}
          onChange={(e) => {
            setRole(e.target.value);
            setExpanded(null);
          }}
        >
          <option value="all">{t('codex.allRoles')}</option>
          {[...new Set(messages.map((m) => m.role))].map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
        <span>
          {visible.length} {t('codex.items2')}
        </span>
      </div>
      {error && <Failure error={error} retry={copyContext} />}
      {visible.map((message) => (
        <section className="app-message" key={message.index}>
          <button
            type="button"
            className="app-message-heading"
            aria-expanded={opened === message.index}
            onClick={() => setExpanded(opened === message.index ? -1 : message.index)}
          >
            <IconChevronRightOutlineRegular
              size={11}
              style={{ transform: opened === message.index ? 'rotate(90deg)' : undefined }}
            />
            <span className="app-role">{message.role}</span>
            <strong title={message.preview || message.label}>
              {message.preview || message.label}
            </strong>
            <em>{message.inherited ? t('codex.inherited') : ''}</em>
            <small>
              {message.chars.toLocaleString()} {t('codex.chars')}
            </small>
          </button>
          {opened === message.index && (
            <>
              <div className="app-message-origin">
                {t('codex.item')} {message.index + 1} ·{' '}
                {message.origin === 'response'
                  ? t('codex.previousModelOutput')
                  : t('codex.requestInput')}
              </div>
              {message.hasEncryptedContent && (
                <p className="app-note">{t('codex.containsOpaqueEncryptedData')}</p>
              )}
              <TextContent
                key={message.index}
                rowId={request.rowId}
                section="message"
                itemIndex={message.index}
                api={api}
                copy={copy}
                label={`${message.role} ${message.label}`}
              />
            </>
          )}
        </section>
      ))}
      {!visible.length && <p className={table.noPayload}>{t('codex.noInputItemsMatchThisRole')}</p>}
      <details className="app-tool-catalog">
        <summary>{t('codex.toolDeclarations')}</summary>
        <TextContent
          rowId={request.rowId}
          section="tools"
          api={api}
          copy={copy}
          label={t('codex.toolDeclarationsJSON')}
        />
      </details>
    </>
  );
}

export function RequestContent({ traceId, request, tab, call, copy }) {
  const t = useTranslation();
  const [detail, setDetail] = useState(null),
    [error, setError] = useState(''),
    [retry, setRetry] = useState(0);
  const api = useCallback((name, args) => call(name, { traceId, ...args }), [traceId, call]);
  useEffect(() => {
    let active = true;
    setDetail(null);
    setError('');
    if (tab === 'codex-prompt')
      api('get_rollout_detail', { rowId: request.rowId })
        .then((value) => {
          if (active) setDetail(value);
        })
        .catch((e) => {
          if (active) setError(e);
        });
    return () => {
      active = false;
    };
  }, [api, request.rowId, tab, retry]);
  if (tab === 'codex-request' || tab === 'codex-response')
    return (
      <TextContent
        rowId={request.rowId}
        section={tab === 'codex-request' ? 'raw_request' : 'response'}
        api={api}
        copy={copy}
        label={`${t(tab === 'codex-request' ? 'codex.request' : 'codex.response')} JSON`}
      />
    );
  if (tab !== 'codex-prompt') return null;
  if (request.purpose === 'compaction')
    return error ? (
      <Failure error={error} retry={() => setRetry((v) => v + 1)} />
    ) : detail ? (
      <section className="app-context-note" aria-label={t('codex.contextCompaction')}>
        <MarkdownText text={compactionText(detail.compaction, t)} />
      </section>
    ) : (
      <Skeleton />
    );
  return error ? (
    <Failure error={error} retry={() => setRetry((v) => v + 1)} />
  ) : detail ? (
    <PromptContext key={request.rowId} {...{ request, detail, api, copy }} />
  ) : (
    <Skeleton />
  );
}
