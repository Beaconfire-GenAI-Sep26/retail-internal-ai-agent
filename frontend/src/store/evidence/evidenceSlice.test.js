// Evidence cache + drawer state: open/close, fetch once per ID, clear on logout.
import { describe, expect, it } from 'vitest';
import { configureStore } from '@reduxjs/toolkit';
import reducer, { openEvidence, closeEvidence } from './evidenceSlice';
import { fetchEvidence } from './evidenceThunks';
import { credentialsCleared } from '../auth/authSlice';

const ID = 'EV-CLM-004410';
const record = { evidence_id: ID, type: 'claim', store_id: 'STORE-A', occurred_at: '2026-11-04T01:12:00Z', summary: 's', attributes: {} };
const initial = reducer(undefined, { type: '@@init' });

describe('evidence slice', () => {
  it('opens and closes the drawer', () => {
    const open = reducer(initial, openEvidence(ID));
    expect(open.openId).toBe(ID);
    expect(reducer(open, closeEvidence()).openId).toBeNull();
  });

  it('caches a fetched record by ID', () => {
    const loading = reducer(initial, fetchEvidence.pending('r1', ID));
    expect(loading.statusById[ID]).toBe('loading');
    const done = reducer(loading, fetchEvidence.fulfilled(record, 'r1', ID));
    expect(done.statusById[ID]).toBe('succeeded');
    expect(done.byId[ID]).toEqual(record);
  });

  it('keeps the error per ID, and a retry clears it', () => {
    const failed = reducer(initial, fetchEvidence.rejected(null, 'r1', ID, 'Not found, or you do not have access to it.'));
    expect(failed.statusById[ID]).toBe('failed');
    expect(failed.errorById[ID]).toMatch(/Not found/);
    const retry = reducer(failed, fetchEvidence.pending('r2', ID));
    expect(retry.errorById[ID]).toBeUndefined();
  });

  it('a session ending clears the cache and closes the drawer', () => {
    const filled = reducer(reducer(initial, fetchEvidence.fulfilled(record, 'r1', ID)), openEvidence(ID));
    expect(reducer(filled, credentialsCleared())).toEqual(initial);
  });

  it('does not fetch an ID that is already cached', async () => {
    const store = configureStore({
      reducer: { evidence: reducer },
      preloadedState: { evidence: { ...initial, byId: { [ID]: record }, statusById: { [ID]: 'succeeded' } } },
    });
    const result = await store.dispatch(fetchEvidence(ID));
    expect(result.meta.condition).toBe(true); // skipped by `condition`, no request made
  });
});
