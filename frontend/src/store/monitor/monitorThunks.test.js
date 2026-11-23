// Monitor thunks against the real-API branch (axios faked): the requests sent,
// what lands in the cache, caching, and errors.
// The fake axios answers with the mock store endpoints, so the bodies have the
// exact Domain ToolResult shape.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { configureStore } from '@reduxjs/toolkit';

vi.mock('../../api/mockAuth', () => ({ USE_MOCKS: false }));
vi.mock('../../api/axios', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  injectStore: vi.fn(),
  invalidateSession: vi.fn(),
  refreshSession: vi.fn(),
}));

const { default: api } = await import('../../api/axios');
const mock = await import('../../api/mocks/mockStores');
const { default: monitor } = await import('./monitorSlice');
const { fetchStoreBase, fetchStoreRange, rangeKey } = await import('./monitorThunks');

const user = { user_id: 'USR-001', role: 'loe_analyst', store_ids: ['STORE-A', 'STORE-B'] };
const makeStore = () => configureStore({ reducer: { monitor, auth: () => ({ user }) } });

// /domain/stores/{id}{path} → the matching mock endpoint
const routeGet = (url, { params } = {}) => {
  const [, id, path] = url.match(/^\/domain\/stores\/([^/]+)(.*)$/);
  const ctx = { user };
  const handler = {
    '': () => mock.mockGetStore(id, ctx),
    '/menu': () => mock.mockGetMenu(id, ctx),
    '/overview': () => mock.mockStoreOverview(id, params ?? {}, ctx),
    '/diagnostics/events': () => mock.mockEventLog(id, params ?? {}, ctx),
  }[path];
  return handler().then((data) => ({ data }));
};
const routePost = (url, body) => {
  const [, id, path] = url.match(/^\/domain\/stores\/([^/]+)(.*)$/);
  const fn = path.endsWith('claim-breakdown') ? mock.mockClaimBreakdown : mock.mockCancellationBreakdown;
  return fn(id, body, { user }).then((data) => ({ data }));
};

beforeEach(() => {
  api.get.mockReset().mockImplementation(routeGet);
  api.post.mockReset().mockImplementation(routePost);
});

describe('fetchStoreBase', () => {
  it('reads the 42-day window first, then the rest for those dates', async () => {
    const store = makeStore();
    await store.dispatch(fetchStoreBase('STORE-A'));

    expect(api.get.mock.calls[0]).toEqual(['/domain/stores/STORE-A/overview', { params: undefined }]);
    expect(api.get).toHaveBeenCalledWith('/domain/stores/STORE-A/diagnostics/events',
      { params: { start: '2026-10-05', end: '2026-11-15' } });
    expect(api.post).toHaveBeenCalledWith('/domain/stores/STORE-A/diagnostics/cancellation-breakdown',
      { filter: { start: '2026-10-05', end: '2026-11-15' }, group_by: 'day' });

    const entry = store.getState().monitor.base['STORE-A'];
    expect(entry.status).toBe('succeeded');
    expect(entry.data.daily).toHaveLength(42);
    expect(entry.data.cancelDaily).toHaveLength(42);
    expect(entry.data.itemNames['ITEM-A-001']).toBe('Orange Chicken');
    // Event dates are store-local: the 10/30 10:00 Chicago menu change
    expect(entry.data.events.map((e) => e.date)).toContain('2026-10-30');
  });

  it('is cached: a second dispatch sends nothing', async () => {
    const store = makeStore();
    await store.dispatch(fetchStoreBase('STORE-A'));
    const calls = api.get.mock.calls.length;
    await store.dispatch(fetchStoreBase('STORE-A'));
    expect(api.get.mock.calls.length).toBe(calls);
  });

  it('a failed load shows the readable error (api/errors.js), and can be retried', async () => {
    api.get.mockRejectedValueOnce({ response: { status: 403, data: { error: { code: 'STORE_NOT_PERMITTED', message: 'No access.' } } } });
    const store = makeStore();
    await store.dispatch(fetchStoreBase('STORE-A'));
    expect(store.getState().monitor.base['STORE-A']).toMatchObject({ status: 'failed', error: 'You do not have access to this store.' });

    await store.dispatch(fetchStoreBase('STORE-A'));
    expect(store.getState().monitor.base['STORE-A'].status).toBe('succeeded');
  });
});

describe('fetchStoreRange', () => {
  it('sends the breakdowns for the range and caches them under store + dates', async () => {
    const store = makeStore();
    const arg = { storeId: 'STORE-B', start: '2026-11-02', end: '2026-11-15' };
    await store.dispatch(fetchStoreRange(arg));

    const groupings = api.post.mock.calls.map(([, body]) => body.group_by).sort();
    expect(groupings).toEqual(['cancellation_category', 'daypart', 'item_id', 'modifier']);
    api.post.mock.calls.forEach(([, body]) => expect(body.filter).toEqual({ start: '2026-11-02', end: '2026-11-15' }));
    expect(api.get).toHaveBeenCalledWith('/domain/stores/STORE-B/overview', { params: { start: '2026-11-02', end: '2026-11-15' } });

    const { data } = store.getState().monitor.ranges[rangeKey('STORE-B', arg)];
    expect(data.dayparts.map((d) => d.key).sort()).toEqual(['dinner', 'late_night', 'lunch']);
    expect(data.errorCategories.missing_item).toBeGreaterThan(0);
    expect(data.cancelCategories.too_busy).toBeGreaterThan(0);
  });
});
