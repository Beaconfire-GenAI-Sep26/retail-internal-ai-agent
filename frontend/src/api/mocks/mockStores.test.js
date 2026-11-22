// Mock store endpoints: same envelope as Domain, store grants, and the seed's story.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as m from './mockStores';
import { parseClaimGroups, parseOverview, sumWindow } from '../../components/monitor/monitorMath';

const analyst = { user_id: 'USR-001', role: 'loe_analyst', store_ids: ['STORE-A', 'STORE-B'] };
const viewer = { user_id: 'USR-002', role: 'viewer', store_ids: ['STORE-A'] };
const ctx = { user: analyst };

// Mock endpoints wait with setTimeout; run them on fake timers
const call = async (fn, ...args) => {
  const p = fn(...args);
  p.catch(() => {});
  await vi.runAllTimersAsync();
  return p;
};
const fail = async (fn, ...args) => {
  try {
    await call(fn, ...args);
  } catch (err) {
    return err.response;
  }
  throw new Error('expected an error');
};

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe('requests', () => {
  it('a store outside the grants is 403 STORE_NOT_PERMITTED, an unknown one 404', async () => {
    expect((await fail(m.mockStoreOverview, 'STORE-B', {}, { user: viewer })).status).toBe(403);
    const res = await fail(m.mockGetStore, 'STORE-Z', { user: { ...analyst, store_ids: ['STORE-Z'] } });
    expect(res.status).toBe(404);
    expect(res.data.error.code).toBe('NOT_FOUND');
  });

  it('overview with no dates covers the 42 days ending on the last day of data', async () => {
    const o = await call(m.mockStoreOverview, 'STORE-A', {}, ctx);
    expect(o.window).toEqual({ start: '2026-10-05', end: '2026-11-15' });
    expect(o.metrics.filter((x) => x.name === 'daily_claim_rate')).toHaveLength(42);
  });

  it('returns the same rows on every call', async () => {
    const a = await call(m.mockStoreOverview, 'STORE-B', {}, ctx);
    const b = await call(m.mockStoreOverview, 'STORE-B', {}, ctx);
    expect(a.metrics).toEqual(b.metrics);
  });
});

describe('the seed story', () => {
  const daily = async (storeId) => parseOverview(await call(m.mockStoreOverview, storeId, {}, ctx)).daily;

  it('STORE-A rises above the 5% goal after the Extra sauce change on 10/30', async () => {
    const rows = await daily('STORE-A');
    expect(sumWindow(rows, { start: '2026-10-05', end: '2026-10-29' }).rate).toBeLessThan(0.03);
    expect(sumWindow(rows, { start: '2026-10-30', end: '2026-11-15' }).rate).toBeGreaterThan(0.05);
    const mods = parseClaimGroups(await call(m.mockClaimBreakdown, 'STORE-A',
      { filter: { start: '2026-10-30', end: '2026-11-15' }, group_by: 'modifier' }, ctx), 'modifier');
    expect(mods.map((x) => x.key)).toEqual(['Extra sauce']);
  });

  it('STORE-B rises from 11/3, at dinner only', async () => {
    const rows = await daily('STORE-B');
    expect(sumWindow(rows, { start: '2026-10-05', end: '2026-11-02' }).rate).toBeLessThan(0.03);
    expect(sumWindow(rows, { start: '2026-11-03', end: '2026-11-15' }).rate).toBeGreaterThan(0.05);
    const parts = parseClaimGroups(await call(m.mockClaimBreakdown, 'STORE-B',
      { filter: { start: '2026-11-03', end: '2026-11-15' }, group_by: 'daypart' }, ctx), 'daypart');
    const rateOf = (k) => { const p = parts.find((x) => x.key === k); return p.claims / p.orders; };
    expect(rateOf('dinner')).toBeGreaterThan(3 * rateOf('lunch'));
  });

  it('events overlap the window — like Domain, one with no ended_at is still in effect', async () => {
    const res = await call(m.mockEventLog, 'STORE-B', { start: '2026-11-02', end: '2026-11-15' }, ctx);
    expect(res.evidence.map((e) => e.attributes.event_type)).toEqual(['menu_change', 'promotion']);
    expect(res.evidence[1].attributes.ended_at).toBeTruthy();
    const before = await call(m.mockEventLog, 'STORE-A', { start: '2026-10-05', end: '2026-10-25' }, ctx);
    expect(before.evidence.map((e) => e.attributes.event_type)).toEqual(['store_downtime']);
  });

  it('cancellations by day give the placed orders as the denominator', async () => {
    const res = await call(m.mockCancellationBreakdown, 'STORE-A',
      { filter: { start: '2026-10-24', end: '2026-10-26' }, group_by: 'day' }, ctx);
    const rates = res.metrics.filter((x) => x.name === 'cancellation_rate');
    expect(rates).toHaveLength(3);
    rates.forEach((r) => expect(r.denominator).toBeGreaterThan(30));
    // The out-of-stock days stand out
    expect(rates.every((r) => r.numerator / r.denominator > 0.05)).toBe(true);
  });
});
