// [14b] TrendChart — M&I rate over time, one line per store (D-06)
// Plain SVG, no chart library (like caseDetail/DailyRateChart, kept separate
// because that one is case-specific). Draws:
//   - one 2px line per store, labeled at its last point
//   - the goal as a dashed line
//   - an event lane per store below the axis: ◆ per day with operational events,
//     and a light band for events that span days (promotions)
//   - a crosshair + tooltip on hover with each store's rate and its sample size


// ═══════════════════════════════════════════════════════════════════
// 1. Imports + layout
// ═══════════════════════════════════════════════════════════════════
import { useState } from 'react';
import useElementWidth from '../../hooks/useElementWidth';
import { EVENT_TYPE_LABELS, formatRate, formatRatio, labelOf } from '../../api/format';
import { shortDay } from './monitorMath';

const HEIGHT_PLOT = 240;
const LANE = 22; // height of one event lane

// Round axis step for the highest value: 8.6% → 2.5% steps
const tickStep = (max) => (max <= 0.1 ? 0.025 : max <= 0.3 ? 0.05 : 0.1);


// ═══════════════════════════════════════════════════════════════════
// 2. TrendChart component
// ═══════════════════════════════════════════════════════════════════
// Props:
//   days     ['YYYY-MM-DD'] — the x-axis, oldest first
//   series   [{ storeId, color, points: [{ date, rate, num, den }] }], points match `days`
//   events   [{ storeId, color, items: [{ id, date, endDate, type, description }] }]
//   goal     goal rate, drawn dashed
//   smooth   rolling window in days (1 = daily), for the tooltip title
//   highlight { start, end } — the chosen range; days before it are dimmed
const TrendChart = ({ days, series, events, goal, smooth, highlight }) => {
  const [ref, width] = useElementWidth();
  const [hover, setHover] = useState(null); // { i } over the plot, { event } over a ◆
  const [tipAt, setTipAt] = useState({ x: 0, y: 0 });

  // ── 2a. Scales ──────────────────────────────────────────────────
  const narrow = width < 560;
  const pad = { top: 12, right: narrow ? 12 : 64, bottom: 28 + events.length * LANE, left: 44 };
  const height = pad.top + HEIGHT_PLOT + pad.bottom;
  const plotW = Math.max(10, width - pad.left - pad.right);
  const rates = series.flatMap((s) => s.points.map((p) => p.rate ?? 0));
  const step = tickStep(Math.max(goal, ...rates));
  const top = Math.max(step * Math.ceil((Math.max(goal, ...rates) * 1.1) / step), step);
  const ticks = Array.from({ length: Math.round(top / step) + 1 }, (_, i) => Math.round(i * step * 1000) / 1000);
  const x = (i) => pad.left + (days.length > 1 ? (i * plotW) / (days.length - 1) : plotW / 2);
  const y = (v) => pad.top + HEIGHT_PLOT - (v / top) * HEIGHT_PLOT;
  const dayIndex = new Map(days.map((d, i) => [d, i]));
  const labelEvery = Math.ceil(days.length / (narrow ? 5 : 9));

  // ── 2b. Lines — a gap where a day has no rate ───────────────────
  const pathOf = (points) =>
    points
      .map((p, i) => (p.rate == null ? null : `${i === 0 || points[i - 1].rate == null ? 'M' : 'L'}${x(i)},${y(p.rate)}`))
      .filter(Boolean)
      .join('');

  // End labels, nudged apart when two lines end close together
  const ends = series
    .map((s) => {
      const i = s.points.findLastIndex((p) => p.rate != null);
      return i < 0 ? null : { s, i, ly: y(s.points[i].rate) };
    })
    .filter(Boolean)
    .sort((a, b) => a.ly - b.ly);
  for (let k = 1; k < ends.length; k += 1) {
    if (ends[k].ly - ends[k - 1].ly < 14) ends[k].ly = ends[k - 1].ly + 14;
  }

  // ── 2c. Hover ───────────────────────────────────────────────────
  const place = (e) => {
    const box = e.currentTarget.closest('.trend-chart').getBoundingClientRect();
    setTipAt({ x: e.clientX - box.left, y: e.clientY - box.top });
  };
  const onPlotMove = (e) => {
    const svg = e.currentTarget.ownerSVGElement.getBoundingClientRect();
    const px = e.clientX - svg.left;
    const i = Math.round(((px - pad.left) / plotW) * (days.length - 1));
    setHover({ i: Math.max(0, Math.min(days.length - 1, i)) });
    place(e);
  };
  const hoverDay = hover?.i != null ? days[hover.i] : null;
  const eventsOn = (day) =>
    events.flatMap((lane) =>
      lane.items
        .filter((ev) => ev.date === day || (ev.endDate && ev.date <= day && day <= ev.endDate))
        .map((ev) => ({ ...ev, storeId: lane.storeId })),
    );

  // ── 2d. Render ──────────────────────────────────────────────────
  return (
    <div className='trend-chart' ref={ref}>
      <svg width={width} height={height} role='img' aria-label='M&I rate by day for each store, with the goal line and operational events'>
        {/* Bands for events that span days */}
        {events.flatMap((lane) =>
          lane.items
            .filter((ev) => ev.endDate && ev.endDate > ev.date)
            .map((ev) => {
              const a = dayIndex.get(ev.date < days[0] ? days[0] : ev.date);
              const b = dayIndex.get(ev.endDate > days.at(-1) ? days.at(-1) : ev.endDate);
              if (a == null || b == null) return null;
              return (
                <g key={`band-${ev.id}`}>
                  <rect x={x(a)} y={pad.top} width={Math.max(2, x(b) - x(a))} height={HEIGHT_PLOT} fill={lane.color} opacity='0.07' />
                  <text x={x(a) + 4} y={pad.top + 12} className='chart-label'>{labelOf(EVENT_TYPE_LABELS, ev.type)}</text>
                </g>
              );
            }),
        )}

        {/* Grid + y axis */}
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.left} x2={pad.left + plotW} y1={y(t)} y2={y(t)} className={t === 0 ? 'chart-axis' : 'chart-grid'} />
            <text x={pad.left - 6} y={y(t) + 4} textAnchor='end' className='chart-label'>
              {`${+(t * 100).toFixed(1)}%`}
            </text>
          </g>
        ))}

        {/* x axis — every Nth day, plus the last one */}
        {days.map((d, i) =>
          (i % labelEvery === 0 && days.length - 1 - i >= labelEvery / 2) || i === days.length - 1 ? (
            <text key={d} x={x(i)} y={pad.top + HEIGHT_PLOT + 16} textAnchor='middle' className='chart-label'>{shortDay(d)}</text>
          ) : null,
        )}

        {/* Goal */}
        <line x1={pad.left} x2={pad.left + plotW} y1={y(goal)} y2={y(goal)} className='chart-goal' />
        <text x={pad.left + plotW - 2} y={y(goal) - 5} textAnchor='end' className='chart-goal-label'>goal {formatRate(goal)}</text>

        {/* Event day guides */}
        {events.flatMap((lane) =>
          [...new Set(lane.items.map((ev) => ev.date))]
            .filter((d) => dayIndex.has(d))
            .map((d) => (
              <line key={`guide-${lane.storeId}-${d}`} x1={x(dayIndex.get(d))} x2={x(dayIndex.get(d))} y1={pad.top} y2={pad.top + HEIGHT_PLOT}
                stroke={lane.color} strokeOpacity='0.35' strokeDasharray='2 3' />
            )),
        )}

        {/* Lines + end labels */}
        {series.map((s) => (
          <path key={s.storeId} d={pathOf(s.points)} fill='none' stroke={s.color} strokeWidth='2' strokeLinejoin='round' strokeLinecap='round' />
        ))}
        {!narrow &&
          ends.map(({ s, i, ly }) => (
            <g key={`end-${s.storeId}`}>
              <circle cx={x(i)} cy={y(s.points[i].rate)} r='4' fill={s.color} stroke='var(--surface)' strokeWidth='2' />
              <text x={x(i) + 8} y={ly + 4} className='chart-end-label'>
                {s.storeId.replace('STORE-', '')} {formatRate(s.points[i].rate)}
              </text>
            </g>
          ))}

        {/* Days before the chosen range: dimmed, drawn over the lines */}
        {highlight && dayIndex.get(highlight.start) > 0 && (() => {
          const hx = (x(dayIndex.get(highlight.start)) + x(dayIndex.get(highlight.start) - 1)) / 2;
          return (
            <g pointerEvents='none'>
              <rect x={pad.left} y={pad.top} width={hx - pad.left} height={HEIGHT_PLOT} className='chart-dim' />
              <line x1={hx} x2={hx} y1={pad.top} y2={pad.top + HEIGHT_PLOT} className='chart-range-edge' />
              <text x={hx + 4} y={pad.top + HEIGHT_PLOT - 6} className='chart-label'>Selected range →</text>
            </g>
          );
        })()}

        {/* Crosshair */}
        {hoverDay && (
          <g pointerEvents='none'>
            <line x1={x(hover.i)} x2={x(hover.i)} y1={pad.top} y2={pad.top + HEIGHT_PLOT} className='chart-crosshair' />
            {series.map((s) =>
              s.points[hover.i]?.rate == null ? null : (
                <circle key={s.storeId} cx={x(hover.i)} cy={y(s.points[hover.i].rate)} r='4' fill={s.color} stroke='var(--surface)' strokeWidth='2' />
              ),
            )}
          </g>
        )}
        <rect x={pad.left} y={pad.top} width={plotW} height={HEIGHT_PLOT} fill='transparent'
          onMouseMove={onPlotMove} onMouseLeave={() => setHover(null)} />

        {/* Event lanes */}
        {events.map((lane, li) => {
          const ly = pad.top + HEIGHT_PLOT + 34 + li * LANE;
          const byDay = new Map();
          for (const ev of lane.items) {
            if (dayIndex.has(ev.date)) byDay.set(ev.date, [...(byDay.get(ev.date) ?? []), ev]);
          }
          return (
            <g key={lane.storeId}>
              <text x={pad.left - 6} y={ly + 4} textAnchor='end' className='chart-label'>{lane.storeId.replace('STORE-', '')}</text>
              <line x1={pad.left} x2={pad.left + plotW} y1={ly} y2={ly} className='chart-lane' />
              {[...byDay].map(([d, list]) => {
                const cx = x(dayIndex.get(d));
                return (
                  <g key={d} tabIndex='0' role='img'
                    aria-label={`${lane.storeId} ${d}: ${list.map((ev) => ev.description).join(' ')}`}
                    onMouseMove={(e) => { setHover({ event: { storeId: lane.storeId, date: d, list } }); place(e); }}
                    onMouseLeave={() => setHover(null)}>
                    <rect x={cx - 10} y={ly - 10} width='20' height='20' fill='transparent' />
                    <path d={`M${cx},${ly - 6}L${cx + 6},${ly}L${cx},${ly + 6}L${cx - 6},${ly}Z`} fill={lane.color} stroke='var(--surface)' strokeWidth='2' />
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>

      {/* Tooltip */}
      {hover && (
        <div className={`chart-tip${tipAt.x > width - 260 ? ' chart-tip-left' : ''}`} style={{ left: tipAt.x, top: tipAt.y }}>
          {hoverDay ? (
            <>
              <strong>{shortDay(hoverDay)}{smooth > 1 ? ` · ${smooth}-day rolling` : ''}</strong>
              {series.map((s) => {
                const p = s.points[hover.i];
                return (
                  <div key={s.storeId} className='chart-tip-row'>
                    <span className='swatch' style={{ background: s.color }} />
                    {s.storeId} <strong>{formatRate(p?.rate)}</strong>
                    {p && <span className='muted'>{formatRatio(p.num, p.den)}</span>}
                  </div>
                );
              })}
              {eventsOn(hoverDay).map((ev) => (
                <div key={ev.id} className='chart-tip-event'>◆ {ev.storeId.replace('STORE-', '')}: {ev.description}</div>
              ))}
            </>
          ) : (
            <>
              <strong>{hover.event.storeId} · {shortDay(hover.event.date)}</strong>
              {hover.event.list.map((ev) => (
                <div key={ev.id} className='chart-tip-event'>
                  <span className='pill'>{labelOf(EVENT_TYPE_LABELS, ev.type)}</span> {ev.description}
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default TrendChart;
