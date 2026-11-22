// [12c] Monitor page — /monitor — any logged-in user (D-06), the landing page
// Store-level dashboard for one store at a time (store dropdown), built only
// from store and order data (no case data):
//   KPIs for the chosen range · M&I rate trend with operational events ·
//   error categories · rate by daypart · top items · cancellations · review status
// The trend always shows all 42 days, with the days before the chosen range
// dimmed, so the baseline before a jump stays visible. "View cases" links go
// to the case queue filtered by store.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router';
import { useDispatch, useSelector } from 'react-redux';
import { selectStoreIds } from '../store/auth/authSelectors';
import useDocumentTitle from '../hooks/useDocumentTitle';
import { fetchStoreBase, fetchStoreRange, rangeKey } from '../store/monitor/monitorThunks';
import { combineStatus, selectMonitorBase, selectMonitorRanges } from '../store/monitor/monitorSelectors';
import {
  CANCELLATION_CATEGORY_LABELS,
  DAYPART_LABELS,
  ERROR_CATEGORY_LABELS,
  formatDayRange,
  formatRate,
  formatRatio,
  labelOf,
} from '../api/format';
import {
  DEFAULT_RANGE,
  DEFAULT_SMOOTH,
  GOAL_RATE,
  daysBetween,
  previousWindow,
  rangeWindow,
  rate,
  rolling,
  STORE_COLORS,
  sumWindow,
} from '../components/monitor/monitorMath';
import MonitorFilters, { Segmented } from '../components/monitor/MonitorFilters';
import KpiRow from '../components/monitor/KpiRow';
import TrendChart from '../components/monitor/TrendChart';
import BarList from '../components/monitor/BarList';
import TopItems from '../components/monitor/TopItems';
import ReviewStatusBar from '../components/monitor/ReviewStatusBar';

// Stable fallback, so useSelector doesn't return a new [] on every render
const NO_STORES = [];


// ═══════════════════════════════════════════════════════════════════
// 2. Small pieces
// ═══════════════════════════════════════════════════════════════════
// A card with a title, an optional note on the right, and its content
const Card = ({ title, note, wide, children }) => (
  <section className={`monitor-card${wide ? ' monitor-card-wide' : ''}`}>
    <div className='monitor-card-head'>
      <h2>{title}</h2>
      {note && <span className='muted'>{note}</span>}
    </div>
    {children}
  </section>
);

// Store color legend — only needed when more than one store shows
const StoreLegend = ({ stores, extra }) =>
  stores.length > 1 || extra ? (
    <div className='chart-legend monitor-legend'>
      {stores.length > 1 &&
        stores.map((s) => (
          <span key={s.storeId}><i className='swatch' style={{ background: s.color }} />{s.storeId}</span>
        ))}
      {extra}
    </div>
  ) : null;

// The same row shape for every BarList card: one bar per store
const barRows = (keys, labels, stores, valueOf) =>
  keys.map((key) => ({
    key,
    label: labelOf(labels, key),
    bars: stores.map((s) => ({ storeId: s.storeId, color: s.color, ...valueOf(s, key) })),
  }));


// Chosen range + the one before it, ending on the store's last day of data;
// null until the store's base data is in
const windowsFor = (base, storeId, days) => {
  const w = base[storeId]?.data?.window;
  if (!w) return null;
  const current = rangeWindow(w.start, w.end, days);
  return { current, previous: previousWindow(w.start, current, days) };
};


// ═══════════════════════════════════════════════════════════════════
// 3. Monitor component
// ═══════════════════════════════════════════════════════════════════
const Monitor = () => {
  // ── 3a. Filters (local — only this page cares) ──────────────────
  const storeIds = useSelector(selectStoreIds) ?? NO_STORES;
  const [storeChoice, setStoreChoice] = useState(null);
  const [range, setRange] = useState(DEFAULT_RANGE);
  const [smooth, setSmooth] = useState(DEFAULT_SMOOTH);
  // One store at a time: the chosen one, or the first grant (nothing chosen
  // yet, or the chosen store is no longer granted)
  const store = storeIds.includes(storeChoice) ? storeChoice : storeIds[0];
  useDocumentTitle(store ? `Monitor · ${store}` : 'Monitor');

  // ── 3b. Store data from Redux ───────────────────────────────────
  const dispatch = useDispatch();
  const base = useSelector(selectMonitorBase);
  const ranges = useSelector(selectMonitorRanges);

  // Loaded = base data and this range's breakdowns are both in the cache
  const statusOf = (storeId, days) => {
    const w = windowsFor(base, storeId, days);
    return combineStatus([base[storeId], w && ranges[rangeKey(storeId, w.current)]]);
  };

  // ── 3c. Load the chosen view — the thunks skip anything already cached ──
  const wanted = windowsFor(base, store, range);
  const wantedStart = wanted?.current.start;
  const wantedEnd = wanted?.current.end;
  useEffect(() => {
    if (store) dispatch(fetchStoreBase(store));
  }, [dispatch, store]);
  useEffect(() => {
    if (wantedStart) dispatch(fetchStoreRange({ storeId: store, start: wantedStart, end: wantedEnd }));
  }, [dispatch, store, wantedStart, wantedEnd]);

  const wantedState = statusOf(store, range);
  const retry = () => {
    dispatch(fetchStoreBase(store));
    if (wanted) dispatch(fetchStoreRange({ storeId: store, ...wanted.current }));
  };

  // ── 3d. Which view to draw ──────────────────────────────────────
  // While a new store or range loads, keep drawing the last view that loaded
  // (dimmed), so the page doesn't collapse to a loading line and jump back.
  const [lastShown, setLastShown] = useState(null);
  if (wantedState.status === 'succeeded' && (lastShown?.store !== store || lastShown?.range !== range)) {
    setLastShown({ store, range }); // set during render: React re-renders before painting
  }
  const keepLast = lastShown && storeIds.includes(lastShown.store)
    && statusOf(lastShown.store, lastShown.range).status === 'succeeded';
  const view = wantedState.status === 'succeeded' ? { store, range } : keepLast ? lastShown : null;
  const stale = view !== null && wantedState.status === 'loading';
  const viewStore = view?.store;
  const viewRange = view?.range;

  // Everything the cards need, as a one-store list (the cards take a list)
  const stores = useMemo(() => {
    if (!viewStore) return [];
    const b = base[viewStore].data;
    const w = windowsFor(base, viewStore, viewRange);
    const r = ranges[rangeKey(viewStore, w.current)].data;
    const period = (win) => win && { claims: sumWindow(b.daily, win), cancels: sumWindow(b.cancelDaily, win) };
    return [{
      storeId: viewStore,
      color: STORE_COLORS[0],
      base: b,
      range: r,
      window: w.current,
      current: period(w.current),
      previous: period(w.previous),
      pendingClaims: r.pendingClaims,
    }];
  }, [viewStore, viewRange, base, ranges]);

  // ── 3e. Render ──────────────────────────────────────────────────
  const shown = stores[0];
  const header = (
    <div className='page-header'>
      <div>
        <h1>Monitor</h1>
        {shown && (
          <p className='muted'>
            {shown.base.store.name}, {shown.base.store.city}
            {' · '}
            {formatDayRange(shown.window.start, shown.window.end)}
            {' · '}store and order data
            {stale && ' · loading…'}
          </p>
        )}
      </div>
      <MonitorFilters storeIds={storeIds} store={store} range={range}
        onChange={(next) => {
          if (next.store) setStoreChoice(next.store);
          if (next.range) setRange(next.range);
        }} />
    </div>
  );

  if (storeIds.length === 0) {
    return <section>{header}<p className='muted'>No stores are granted to this account.</p></section>;
  }
  if (wantedState.status === 'failed') {
    return (
      <section>
        {header}
        <div className='error' role='alert'>
          <p>{wantedState.error}</p>
          <button type='button' onClick={retry}>Retry</button>
        </div>
      </section>
    );
  }
  if (!shown) {
    return <section>{header}<p className='muted'>Loading store data…</p></section>;
  }

  // Trend: every day of the store's data
  const days = daysBetween(shown.base.window.start, shown.base.window.end);
  const series = stores.map((s) => {
    const byDay = new Map(rolling(s.base.daily, smooth).map((p) => [p.date, p]));
    return { storeId: s.storeId, color: s.color, points: days.map((d) => byDay.get(d) ?? { date: d, rate: null, num: 0, den: 0 }) };
  });
  const events = stores.map((s) => ({ storeId: s.storeId, color: s.color, items: s.base.events }));
  const highlight = shown.window;

  const dayparts = Object.keys(DAYPART_LABELS).filter((k) =>
    stores.some((s) => s.range?.dayparts.some((d) => d.key === k && d.orders > 0)));

  return (
    <section className='monitor'>
      {header}

      <div className={stale ? 'monitor-body is-stale' : 'monitor-body'} aria-busy={stale}>
        <KpiRow stores={stores} days={viewRange} goal={GOAL_RATE} />

        <div className='monitor-grid'>
          <Card title='M&I rate trend' note='Attributable claims ÷ delivered orders · ◆ operational events' wide>
            <div className='monitor-card-tools'>
              <StoreLegend stores={stores} extra={<span className='legend-goal'>Goal</span>} />
              <Segmented label='Smoothing' value={smooth} onChange={setSmooth}
                options={[{ value: 7, label: '7-day rolling' }, { value: 1, label: 'Daily' }]} />
            </div>
            <TrendChart days={days} series={series} events={events} goal={GOAL_RATE} smooth={smooth} highlight={highlight} />
            <div className='case-links'>
              <span className='muted'>View cases:</span>
              {stores.map((s) => (
                <Link key={s.storeId} to={`/cases?store_id=${s.storeId}`}>
                  <i className='swatch' style={{ background: s.color }} />{s.storeId} →
                </Link>
              ))}
            </div>
          </Card>

          <Card title='Error categories' note='Attributable claims'>
            <StoreLegend stores={stores} />
            <BarList labelW={120} rows={barRows(Object.keys(ERROR_CATEGORY_LABELS), ERROR_CATEGORY_LABELS, stores, (s, k) => {
              const n = s.range.errorCategories[k] ?? 0;
              return { value: n, text: String(n), title: `${s.storeId} · ${n} claims` };
            })} />
          </Card>

          <Card title='M&I rate by daypart' note='Dashed line = goal'>
            <StoreLegend stores={stores} extra={<span className='legend-goal'>Goal {formatRate(GOAL_RATE)}</span>} />
            <BarList labelW={90} refValue={GOAL_RATE} rows={barRows(dayparts, DAYPART_LABELS, stores, (s, k) => {
              const d = s.range.dayparts.find((x) => x.key === k);
              const v = d ? rate(d.claims, d.orders) : null;
              return {
                value: v ?? 0,
                text: v == null ? '—' : formatRate(v),
                title: d ? `${s.storeId} · ${formatRatio(d.claims, d.orders)} claims / delivered orders` : `${s.storeId} · no orders`,
              };
            })} />
          </Card>

          <Card title='Top items' note='Most attributable claims'>
            <TopItems stores={stores.map((s) => ({
              storeId: s.storeId, color: s.color, items: s.range.items, modifiers: s.range.modifiers, itemNames: s.base.itemNames,
            }))} />
          </Card>

          <Card title='Cancellation reasons' note='Canceled orders'>
            <StoreLegend stores={stores} />
            <BarList labelW={150} rows={barRows(Object.keys(CANCELLATION_CATEGORY_LABELS), CANCELLATION_CATEGORY_LABELS, stores, (s, k) => {
              const n = s.range.cancelCategories[k] ?? 0;
              return { value: n, text: String(n), title: `${s.storeId} · ${n} canceled orders` };
            })} />
          </Card>

          <Card title='Claim review status' note='All claims, including ones not counted in the rate' wide>
            <ReviewStatusBar stores={stores.map((s) => ({ storeId: s.storeId, counts: s.range.reviewLabels }))} />
          </Card>
        </div>
      </div>
    </section>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 4. Export
// ═══════════════════════════════════════════════════════════════════
export default Monitor;
