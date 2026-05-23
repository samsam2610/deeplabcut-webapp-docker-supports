// Tiny synchronous pub/sub powering VideoViewer's hook bus. Pure, no DOM.
// emit() snapshots its listener set so a callback may unsubscribe during dispatch.

export function makeEventBus() {
  const listeners = new Map(); // event -> Set<cb>
  return {
    on(event, cb) {
      if (!listeners.has(event)) listeners.set(event, new Set());
      listeners.get(event).add(cb);
      return () => {
        const set = listeners.get(event);
        if (set) set.delete(cb);
      };
    },
    emit(event, ...args) {
      const set = listeners.get(event);
      if (!set) return;
      for (const cb of [...set]) cb(...args);
    },
  };
}
