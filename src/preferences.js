// Shared for every recording in this app. Storage failures keep the in-memory preference.
export function createBooleanPreference(
  key,
  { storage = () => globalThis.localStorage, fallback = false } = {},
) {
  let value = fallback;
  try {
    const saved = JSON.parse(storage()?.getItem(key) ?? 'null');
    if (typeof saved === 'boolean') value = saved;
  } catch {}
  const listeners = new Set();
  const notify = () => {
    for (const listener of listeners) listener();
  };
  const receive = (event) => {
    if (event.key !== key) return;
    try {
      const saved = JSON.parse(event.newValue ?? 'null');
      const next = typeof saved === 'boolean' ? saved : fallback;
      if (next !== value) {
        value = next;
        notify();
      }
    } catch {}
  };
  return {
    getSnapshot: () => value,
    subscribe(listener) {
      if (!listeners.size && typeof window !== 'undefined')
        window.addEventListener('storage', receive);
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
        if (!listeners.size && typeof window !== 'undefined')
          window.removeEventListener('storage', receive);
      };
    },
    set(next) {
      if (typeof next !== 'boolean' || next === value) return;
      value = next;
      try {
        storage()?.setItem(key, JSON.stringify(next));
      } catch {}
      notify();
    },
  };
}

export const durationPreference = createBooleanPreference('rollout-viewer.trajectory.duration');
export const wrappingPreference = createBooleanPreference('rollout-viewer.trajectory.wrapping');
