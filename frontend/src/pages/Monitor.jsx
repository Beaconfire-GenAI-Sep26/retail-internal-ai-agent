// [12c] Monitor page — /monitor — any logged-in user (D-06), the landing page
// Store-level dashboard built only from store and order data (no case data):
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
  ALL_STORES,
  DEFAULT_RANGE,
  DEFAULT_SMOOTH,
  GOAL_RATE,
  daysBetween,
  previousWindow,
  rangeWindow,
  rate,
  rolling,
  storeColor,
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


// ═══════════════════════════════════════════════════════════════════
// 3. Monitor component
// ═══════════════════════════════════════════════════════════════════
const Monitor = () => {
  // ── 3a. Filters (local — only this page cares) ──────────────────
  const storeIds = useSelector(selectStoreIds) ?? NO_STORES;
  const [storeChoice, setStoreChoice] = useState(ALL_STORES);
  const [range, setRange] = useState(DEFAULT_RANGE);
  const [smooth, setSmooth] = useState(DEFAULT_SMOOTH);
  // One grant → that store; a stale choice (store no longer granted) → all
  const store = storeIds.length === 1
    ? storeIds[0]
    : storeChoice === ALL_STORES || storeIds.includes(storeChoice) ? storeChoice : ALL_STORES;
  const visible = useMemo(() => (store === ALL_STORES ? storeIds : [store]), [store, storeIds]);

  // ── 3b. Store data from Redux ───────────────────────────────────
  const dispatch = useDispatch();
  const base = useSelector(selectMonitorBase);
  const ranges = useSelector(selectMonitorRanges);

  // Chosen range + the one before it, per store (each ends on its last day of data)
  const windows = useMemo(() => {
    const out = {};
    for (const id of visible) {
      const w = base[id]?.data?.window;
      if (!w) continue;
      const current = rangeWindow(w.start, w.end, range);
      out[id] = { current, previous: previousWindow(w.start, current, range) };
    }
    return out;
  }, [base, visible, range]);

  // ── 3c. Load — the thunks skip anything already cached ──────────
  useEffect(() => {
    visible.forEach((id) => dispatch(fetchStoreBase(id)));
  }, [dispatch, visible]);
  useEffect(() => {
    Object.entries(windows).forEach(([storeId, w]) => dispatch(fetchStoreRange({ storeId, ...w.current })));
  }, [dispatch, windows]);

  const baseState = combineStatus(visible.map((id) => base[id]));
  const rangeState = combineStatus(visible.map((id) => windows[id] && ranges[rangeKey(id, windows[id].current)]));
  const retry = () =>
    visible.forEach((id) => {
      dispatch(fetchStoreBase(id));
      if (windows[id]) dispatch(fetchStoreRange({ storeId: id, ...windows[id].current }));
    });

  // ── 3d. Everything the cards need, per visible store ────────────
  const stores = useMemo(() => {
    if (baseState.status !== 'succeeded') return [];
    return visible.map((id) => {
      const b = base[id].data;
      const w = windows[id];
      const r = ranges[rangeKey(id, w.current)]?.data ?? null;
      const period = (win) => win && { claims: sumWindow(b.daily, win), cancels: sumWindow(b.cancelDaily, win) };
      return {
        storeId: id,
        color: storeColor(storeIds, id),
        base: b,
        range: r,
        current: period(w.current),
        previous: period(w.previous),
        pendingClaims: r?.pendingClaims ?? null,
      };
    });
  }, [baseState.status, visible, base, windows, ranges, storeIds]);

  // ── 3e. Render ──────────────────────────────────────────────────
  const header = (
    <div className='page-header'>
      <div>
        <h1>Monitor</h1>
        {stores[0] && (
          <p className='muted'>
            {formatDayRange(windows[stores[0].storeId].current.start, windows[stores[0].storeId].current.end)}
            {' · '}store and order data
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
  if (baseState.status === 'failed') {
    return (
      <section>
        {header}
        <div className='error' role='alert'>
          <p>{baseState.error}</p>
          <button type='button' onClick={retry}>Retry</button>
        </div>
      </section>
    );
  }
  if (baseState.status !== 'succeeded') {
    return <section>{header}<p className='muted'>Loading store data…</p></section>;
  }

  // Trend: every day any visible store has data
  const first = stores.map((s) => s.base.window.start).sort()[0];
  const last = stores.map((s) => s.base.window.end).sort().at(-1);
  const days = daysBetween(first, last);
  const series = stores.map((s) => {
    const byDay = new Map(rolling(s.base.daily, smooth).map((p) => [p.date, p]));
    return { storeId: s.storeId, color: s.color, points: days.map((d) => byDay.get(d) ?? { date: d, rate: null, num: 0, den: 0 }) };
  });
  const events = stores.map((s) => ({ storeId: s.storeId, color: s.color, items: s.base.events }));
  const highlight = windows[stores[0].storeId].current;

  // Range cards wait for every store's breakdowns
  const rangeBody = (render) => {
    if (rangeState.status === 'failed') {
      return (
        <div className='error' role='alert'>
          <p>{rangeState.error}</p>
          <button type='button' onClick={retry}>Retry</button>
        </div>
      );
    }
    if (rangeState.status !== 'succeeded') return <p className='muted'>Loading…</p>;
    return render();
  };
  const dayparts = Object.keys(DAYPART_LABELS).filter((k) =>
    stores.some((s) => s.range?.dayparts.some((d) => d.key === k && d.orders > 0)));

  return (
    <section className='monitor'>
      {header}

      <KpiRow stores={stores} days={range} goal={GOAL_RATE} />

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
          {rangeBody(() => (
            <>
              <StoreLegend stores={stores} />
              <BarList labelW={120} rows={barRows(Object.keys(ERROR_CATEGORY_LABELS), ERROR_CATEGORY_LABELS, stores, (s, k) => {
                const n = s.range.errorCategories[k] ?? 0;
                return { value: n, text: String(n), title: `${s.storeId} · ${n} claims` };
              })} />
            </>
          ))}
        </Card>

        <Card title='M&I rate by daypart' note='Dashed line = goal'>
          {rangeBody(() => (
            <>
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
            </>
          ))}
        </Card>

        <Card title='Top items' note='Most attributable claims'>
          {rangeBody(() => (
            <TopItems stores={stores.map((s) => ({
              storeId: s.storeId, color: s.color, items: s.range.items, modifiers: s.range.modifiers, itemNames: s.base.itemNames,
            }))} />
          ))}
        </Card>

        <Card title='Cancellation reasons' note='Canceled orders'>
          {rangeBody(() => (
            <>
              <StoreLegend stores={stores} />
              <BarList labelW={150} rows={barRows(Object.keys(CANCELLATION_CATEGORY_LABELS), CANCELLATION_CATEGORY_LABELS, stores, (s, k) => {
                const n = s.range.cancelCategories[k] ?? 0;
                return { value: n, text: String(n), title: `${s.storeId} · ${n} canceled orders` };
              })} />
            </>
          ))}
        </Card>

        <Card title='Claim review status' note='All claims, including ones not counted in the rate' wide>
          {rangeBody(() => (
            <ReviewStatusBar stores={stores.map((s) => ({ storeId: s.storeId, counts: s.range.reviewLabels }))} />
          ))}
        </Card>
      </div>
    </section>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 4. Export
// ═══════════════════════════════════════════════════════════════════
export default Monitor;
