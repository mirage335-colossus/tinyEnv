// Only replaceable visual snapshots are coalesced. Client receipts, operations,
// errors and service dispatch remain synchronous on the accepted-state path.
export function createBrowserPresenter(render, scheduler = globalThis) {
  let pending = null, frame = null, stopped = false, first = true, service = null;
  const cancel = () => {
    if (frame === null) return;
    if (scheduler.requestAnimationFrame) scheduler.cancelAnimationFrame(frame);
    else scheduler.clearTimeout(frame);
    frame = null;
  };
  const flush = () => {
    cancel();
    if (stopped || pending === null) return;
    const snapshot = pending; pending = null; render(snapshot);
  };
  return {
    accept(state) {
      if (stopped) return;
      const nextService = state.service?.id ?? null;
      const barrier = first || service !== nextService || Boolean(state.error) || state.snapshot.closed;
      first = false; service = nextService; pending = state.snapshot;
      if (barrier) flush();
      else if (frame === null) {
        frame = scheduler.requestAnimationFrame ? scheduler.requestAnimationFrame(flush) : scheduler.setTimeout(flush, 0);
      }
      if (state.snapshot.closed) { stopped = true; cancel(); }
    },
    flush,
    close() { stopped = true; pending = null; cancel(); }
  };
}
