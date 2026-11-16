import { apiError } from './errors.js';
import React from 'react';
import { ImageGallery } from '../vendor/dsh/packages/client/ui-attachment/src/MessageImage.tsx';
import { FileTransfers } from '../vendor/dsh/packages/client/ui-file-drag/src/client/transfers.ts';
import { useTranslation } from './locale-context.jsx';

// Labels match the pinned conversation image dictionary. Only the byte loader
// and browser drag transport differ from DSH's Gateway-backed attachment store.
const cache = new Map();
let cachedBytes = 0;
export const loadImage = (attachment) => {
  const id = attachment.attachmentId,
    existing = cache.get(id);
  if (existing) return existing.promise;
  const entry = { url: null, size: 0, promise: null };
  entry.promise = Promise.resolve()
    .then(async () => {
      const url = attachment.recordedUrl;
      if (typeof url !== 'string' || !url.startsWith('data:image/'))
        throw apiError({ errorCode: 'image_unavailable' });
      const probe = new Image();
      probe.src = url;
      await probe.decode();
      entry.url = url;
      entry.size = url.length * 2;
      cachedBytes += entry.size;
      for (const [key, item] of cache) {
        if (cache.size <= 64 && cachedBytes <= 16 * 1024 * 1024) break;
        cache.delete(key);
        cachedBytes -= item.size;
      }
      return url;
    })
    .catch((error) => {
      if (cache.get(id) === entry) cache.delete(id);
      throw error;
    });
  cache.set(id, entry);
  return entry.promise;
};
loadImage.peek = (attachment) => cache.get(attachment.attachmentId)?.url ?? undefined;

const reportDragFailure = () =>
  window.dispatchEvent(
    new CustomEvent('rollout-viewer:notice', {
      detail: apiError({ errorCode: 'image_drag_failed' }),
    }),
  );
let transfers;
const fileDrag = {
  async prepare(source, signal) {
    if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
    let blob = source.blob;
    if (!blob) {
      if (!source.url.startsWith('data:image/')) throw apiError({ errorCode: 'image_unavailable' });
      const comma = source.url.indexOf(','),
        header = source.url.slice(0, comma),
        encoded = source.url.slice(comma + 1);
      const bytes = header.includes(';base64')
        ? Uint8Array.from(atob(encoded), (value) => value.charCodeAt(0))
        : new TextEncoder().encode(decodeURIComponent(encoded));
      blob = new Blob([bytes], { type: header.slice(5).split(';')[0] });
    }
    transfers ??= new FileTransfers(undefined, reportDragFailure);
    return transfers.prepare(
      { ...source, kind: 'blob', blob, mediaType: source.mediaType || blob.type },
      signal,
    );
  },
  reportFailure: reportDragFailure,
};
export function disposeImageTransfers() {
  transfers?.dispose();
  transfers = undefined;
}
const getTriggerProps = () => ({});
function RecordedGallery(props) {
  const t = useTranslation();
  const labels = {
    image: t('codex.image'),
    open: t('codex.viewOriginalImage'),
    openNamed: (label) => t('codex.viewOriginalImage2', { value1: label }),
    loading: t('codex.loadingImage'),
    loadFailed: t('codex.imageFailedToLoadRetry'),
    lightbox: {
      dialog: t('codex.originalImagePreview'),
      close: t('codex.closeOriginalImagePreview'),
    },
  };
  return (
    <ImageGallery
      {...props}
      load={loadImage}
      labels={labels}
      fileDrag={fileDrag}
      getTriggerProps={getTriggerProps}
    />
  );
}
export function renderImageSlot(_, props) {
  return <RecordedGallery {...props} />;
}
