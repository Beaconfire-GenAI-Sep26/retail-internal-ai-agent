// Monitor dashboard math: date windows, rolling rates, deltas, ToolResult parsing.
import { describe, expect, it } from 'vitest';
import {
  addDays,
  daysBetween,
  delta,
  parseClaimGroups,
  parseEvents,
  parseOverview,
  previousWindow,
  rangeWindow,
  rolling,
  sumWindow,
} from './monitorMath';

const metric = (name, group, numerator, denominator, value = null, unit = 'rate') =>
  ({ name, group, value, numerator, denominator, unit });

describe('dates', () => {
  it('adds days across a month end, with no time zone shift', () => {
    expect(addDays('2026-10-30', 3)).toBe('2026-11-02');
    expect(addDays('2026-11-01', -1)).toBe('2026-10-31');
  });

  it('lists every day of a window, inclusive', () => {
    expect(daysBetween('2026-10-30', '2026-11-02')).toEqual(['2026-10-30', '2026-10-31', '2026-11-01', '2026-11-02']);
  });

  it('the range ends on the last day of data, and its previous period sits right before it', () => {
    const current = rangeWindow('2026-10-05', '2026-11-15', 14);
    expect(current).toEqual({ start: '2026-11-02', end: '2026-11-15' });
    expect(previousWindow('2026-10-05', current, 14)).toEqual({ start: '2026-10-19', end: '2026-11-01' });
  });

  it('the full 42 days has no previous period, and a range never starts before the data', () => {
    const all = rangeWindow('2026-10-05', '2026-11-15', 42);
    expect(all).toEqual({ start: '2026-10-05', end: '2026-11-15' });
    expect(previousWindow('2026-10-05', all, 42)).toBeNull();
    expect(rangeWindow('2026-11-10', '2026-11-15', 14).start).toBe('2026-11-10');
  });
});

describe('rates', () => {
  const rows = [
    { date: '2026-11-01', num: 1, den: 50 },
    { date: '2026-11-02', num: 3, den: 50 },
    { date: '2026-11-03', num: 5, den: 0 },
    { date: '2026-11-04', num: 2, den: 100 },
  ];

  it('sums numerators and denominators inside the window, not the daily rates', () => {
    expect(sumWindow(rows, { start: '2026-11-02', end: '2026-11-04' })).toEqual({ num: 10, den: 150, rate: 10 / 150 });
  });

  it('no orders → null rate, never 0', () => {
    expect(sumWindow(rows, { start: '2026-11-03', end: '2026-11-03' }).rate).toBeNull();
  });

  it('rolling averages over fewer days at the start', () => {
    const r = rolling(rows, 2);
    expect(r[0]).toMatchObject({ num: 1, den: 50, rate: 0.02 });
    expect(r[1]).toMatchObject({ num: 4, den: 100, rate: 0.04 });
    expect(r[2]).toMatchObject({ num: 8, den: 50 });
    expect(rolling(rows, 1)[2].rate).toBeNull();
  });

  it('delta: rates in points, counts in percent, nothing without a previous value', () => {
    expect(delta(0.061, 0.021, 'pt').text).toBe('4.0pt');
    expect(delta(80, 100, 'pct')).toEqual({ diff: -20, text: '20%' });
    expect(delta(0.05, null, 'pt')).toBeNull();
    expect(delta(5, 0, 'pct')).toBeNull();
  });
});

describe('ToolResult parsing', () => {
  it('store_overview → daily rows (sorted), counts and pending claims', () => {
    const o = parseOverview({
      window: { start: '2026-11-01', end: '2026-11-02' },
      pending_claims: 4,
      metrics: [
        metric('claim_rate', null, 9, 100, 0.09),
        metric('daily_claim_rate', 'day=2026-11-02', 5, 50),
        metric('daily_claim_rate', 'day=2026-11-01', 4, 50),
        metric('claim_count', 'review_label=store_fault', null, null, 7, 'count'),
        metric('claim_count', 'error_category=missing_item', null, null, 3, 'count'),
      ],
    });
    expect(o.daily).toEqual([
      { date: '2026-11-01', num: 4, den: 50 },
      { date: '2026-11-02', num: 5, den: 50 },
    ]);
    expect(o.reviewLabels).toEqual({ store_fault: 7 });
    expect(o.errorCategories).toEqual({ missing_item: 3 });
    expect(o.pendingClaims).toBe(4);
  });

  it('claim_breakdown → only claim_rate rows of the asked dimension', () => {
    const groups = parseClaimGroups({
      metrics: [
        metric('claim_rate', 'daypart=dinner', 12, 300),
        metric('claim_share', 'daypart=dinner', 12, 20, 0.6, 'share'),
        metric('claim_rate', 'item_id=unknown', 2, null),
      ],
    }, 'daypart');
    expect(groups).toEqual([{ key: 'dinner', claims: 12, orders: 300 }]);
  });

  it('event_log → store-local dates; ended_at is exclusive', () => {
    const toDate = (iso) => new Date(iso).toLocaleDateString('en-CA', { timeZone: 'America/Chicago' });
    const [ev] = parseEvents({
      evidence: [{
        evidence_id: 'EV-EVT-1',
        occurred_at: '2026-11-03T06:00:00Z',
        attributes: { event_type: 'promotion', started_at: '2026-11-03T06:00:00Z', ended_at: '2026-11-10T06:00:00Z', description: 'Promo' },
      }],
    }, toDate);
    expect(ev).toEqual({ id: 'EV-EVT-1', date: '2026-11-03', endDate: '2026-11-09', type: 'promotion', description: 'Promo' });
  });
});
