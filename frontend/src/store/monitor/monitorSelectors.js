// [08c] Monitor selectors — how the Monitor page reads state.monitor
// The page shows several stores at once, so it reads the two cache maps and
// picks its entries with the helpers below (no new arrays → no extra renders).


// ═══════════════════════════════════════════════════════════════════
// 1. Selectors
// ═══════════════════════════════════════════════════════════════════
export const selectMonitorBase = (state) => state.monitor.base;
export const selectMonitorRanges = (state) => state.monitor.ranges;


// ═══════════════════════════════════════════════════════════════════
// 2. Combining entries — what the page shows while some stores still load
// ═══════════════════════════════════════════════════════════════════
// entries: cache entries (or undefined) → 'loading' | 'failed' | 'succeeded'
// One failed store fails the view (with its message); any missing or loading
// store keeps it loading.
export const combineStatus = (entries) => {
  const failed = entries.find((e) => e?.status === 'failed');
  if (failed) return { status: 'failed', error: failed.error };
  if (entries.some((e) => e?.status !== 'succeeded')) return { status: 'loading', error: null };
  return { status: 'succeeded', error: null };
};
