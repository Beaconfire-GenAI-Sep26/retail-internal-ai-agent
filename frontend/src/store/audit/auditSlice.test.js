// Audit slice: entries per case, newest-first sorting, cleared on logout
import { describe, expect, it } from 'vitest';
import reducer from './auditSlice';
import { fetchAudit } from './auditThunks';
import { newestFirst, selectAuditEntries } from './auditSelectors';
import { credentialsCleared } from '../auth/authSlice';

const row = (audit_id, at) => ({ audit_id, at, case_id: 'CASE-0001', action: 'x' });
const initial = reducer(undefined, { type: '@@init' });

describe('audit slice', () => {
  it('stores the entries of the case asked for', () => {
    let s = reducer(initial, fetchAudit.pending('r1', 'CASE-0001'));
    s = reducer(s, fetchAudit.fulfilled([row('AUD-000001', '2026-11-16T15:00:00Z')], 'r1', 'CASE-0001'));
    expect(selectAuditEntries({ audit: s }, 'CASE-0001')).toHaveLength(1);
    expect(selectAuditEntries({ audit: s }, 'CASE-0002')).toEqual([]);
  });

  it('a refresh keeps the rows on screen; another case starts empty', () => {
    const filled = reducer(reducer(initial, fetchAudit.pending('r1', 'CASE-0001')),
      fetchAudit.fulfilled([row('AUD-000001', '2026-11-16T15:00:00Z')], 'r1', 'CASE-0001'));
    expect(reducer(filled, fetchAudit.pending('r2', 'CASE-0001')).entries).toHaveLength(1);
    expect(reducer(filled, fetchAudit.pending('r3', 'CASE-0002')).entries).toEqual([]);
  });

  it('a late answer for a case already left is ignored', () => {
    let s = reducer(initial, fetchAudit.pending('r1', 'CASE-0001'));
    s = reducer(s, fetchAudit.pending('r2', 'CASE-0002'));
    s = reducer(s, fetchAudit.fulfilled([row('AUD-000001', '2026-11-16T15:00:00Z')], 'r1', 'CASE-0001'));
    expect(s.caseId).toBe('CASE-0002');
    expect(s.entries).toEqual([]);
  });

  it('newest first; same time → higher audit_id first', () => {
    const sorted = newestFirst([
      row('AUD-000001', '2026-11-16T15:00:00Z'),
      row('AUD-000003', '2026-11-16T16:00:00Z'),
      row('AUD-000002', '2026-11-16T15:00:00Z'),
    ]);
    expect(sorted.map((r) => r.audit_id)).toEqual(['AUD-000003', 'AUD-000002', 'AUD-000001']);
  });

  it('cleared when the session ends', () => {
    const filled = reducer(initial, fetchAudit.pending('r1', 'CASE-0001'));
    expect(reducer(filled, credentialsCleared())).toEqual(initial);
  });
});
