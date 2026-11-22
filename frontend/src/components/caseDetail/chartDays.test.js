// The chart's date helpers: extending the axis past the data for a run recheck.
import { describe, expect, it } from 'vitest';
import { addDays, chartDays, latestRanRecheck } from './chartDays';

const day = (date) => ({ date, rate: 0.05, claims: 5, eligible_orders: 100 });

describe('addDays', () => {
  it('crosses month ends and DST without shifting the date', () => {
    expect(addDays('2026-11-15', 1)).toBe('2026-11-16');
    expect(addDays('2026-11-30', 1)).toBe('2026-12-01');
    expect(addDays('2026-10-31', 2)).toBe('2026-11-02'); // US DST ends Nov 1
  });
});

describe('latestRanRecheck', () => {
  it('skips scheduled rechecks and picks the one that ran last', () => {
    const first = { recheck_id: 'R1', status: 'not_improved', after: {}, ran_at: '2026-11-21T10:00:00Z' };
    const second = { recheck_id: 'R2', status: 'improved', after: {}, ran_at: '2026-11-21T12:00:00Z' };
    const scheduled = { recheck_id: 'R3', status: 'scheduled', after: null, ran_at: null };
    expect(latestRanRecheck([second, first, scheduled])).toBe(second);
    expect(latestRanRecheck([scheduled])).toBeNull();
    expect(latestRanRecheck(undefined)).toBeNull();
  });
});

describe('chartDays', () => {
  const rates = [day('2026-11-14'), day('2026-11-15')];

  it('no recheck → just the daily rates', () => {
    expect(chartDays(rates, null)).toEqual(rates);
  });

  it('a run recheck → empty days up to the end of its after window', () => {
    const days = chartDays(rates, { after: { start: '2026-11-16', end: '2026-11-18' } });
    expect(days.map((d) => d.date)).toEqual(['2026-11-14', '2026-11-15', '2026-11-16', '2026-11-17', '2026-11-18']);
    expect(days.slice(2).every((d) => d.future)).toBe(true);
  });
});
