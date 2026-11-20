// Display rules from ui-workflow.md v0.3 "Display rules": null rates, sample
// sizes, store timezone, Target text and the investigation error messages.
import { describe, expect, it } from 'vitest';
import {
  formatRate,
  formatRateWindow,
  formatDateTime,
  formatDay,
  formatTarget,
  formatMoney,
  formatInvestigationError,
  labelOf,
  CAUSE_LABELS,
  INVESTIGATION_ERROR_MESSAGES,
} from './format';

describe('rates', () => {
  it('null rate never shows as 0%', () => {
    expect(formatRate(null)).toBe('Not enough data');
    expect(formatRate(0)).toBe('0.0%');
  });

  it('a RateWindow shows its sample size', () => {
    expect(formatRateWindow({ claims: 12, eligible_orders: 240, rate: 0.05 })).toBe('12 / 240 (5.0%)');
  });

  it('a RateWindow with rate null still shows its sample size', () => {
    expect(formatRateWindow({ claims: 3, eligible_orders: 40, rate: null })).toBe('3 / 40 · Not enough data');
  });
});

describe('formatDay', () => {
  it('a store-local date stays the same day in any browser timezone', () => {
    expect(formatDay('2026-10-30')).toBe('Oct 30, 2026');
    expect(formatDay(null)).toBe('—');
  });
});

describe('formatDateTime', () => {
  it("shows the store's local time, not UTC", () => {
    // 01:12 UTC on Nov 4 is still Nov 3 in Chicago
    expect(formatDateTime('2026-11-04T01:12:00Z', 'America/Chicago')).toBe('Nov 3, 2026, 7:12 PM CST');
    expect(formatDateTime('2026-11-04T01:12:00Z', 'America/New_York')).toBe('Nov 3, 2026, 8:12 PM EST');
  });

  it('missing time → a dash', () => {
    expect(formatDateTime(null, 'America/Chicago')).toBe('—');
  });
});

describe('formatTarget', () => {
  it('joins daypart, order size, items and modifiers', () => {
    expect(formatTarget({ daypart: ['dinner'], item_count_min: 5, item_id: [], modifiers: ['Extra sauce'] }))
      .toBe('dinner · 5+ items · Extra sauce');
  });

  it('keeps several values of one field', () => {
    expect(formatTarget({ daypart: ['lunch', 'late_night'], item_count_min: null, item_id: ['ITEM-B-007'], modifiers: [] }))
      .toBe('lunch · late night · ITEM-B-007');
  });

  it('nothing set → all orders', () => {
    expect(formatTarget({ daypart: [], item_count_min: null, item_id: [], modifiers: [] })).toBe('All orders');
  });
});

describe('labels', () => {
  it('unknown enum value shows as-is', () => {
    expect(labelOf(CAUSE_LABELS, 'packing')).toBe('Packing');
    expect(labelOf(CAUSE_LABELS, 'new_cause')).toBe('new_cause');
  });

  it('has a message for each of the 8 investigation error codes', () => {
    expect(Object.keys(INVESTIGATION_ERROR_MESSAGES)).toHaveLength(8);
    expect(formatInvestigationError('RUN_TIMEOUT')).toMatch(/time limit/);
  });

  it('unknown or missing error code → the INTERNAL message', () => {
    expect(formatInvestigationError('SOMETHING_NEW')).toBe(INVESTIGATION_ERROR_MESSAGES.INTERNAL);
    expect(formatInvestigationError(null)).toBe(INVESTIGATION_ERROR_MESSAGES.INTERNAL);
  });

  it('money has two decimals', () => {
    expect(formatMoney(1.5)).toBe('$1.50');
  });
});
