// [10g] DailyRateChart — the case "history": one bar per day for 42 days
// Plain SVG, no chart library. Bars inside the trigger window are red on a
// tinted band, and a dashed line marks the goal, so the analyst sees when the
// rate jumped. Once the agent has a diagnosis, a purple line marks the day it
// says the cause started (InvestigationResult.cause_started_at) — data the page
// already has, so no events call.
//
// After a recheck has run (D-05), the x-axis extends to the end of its `after`
// window. Domain has no daily rates past the last day of data, so that part has
// no bars, only the recheck's averages as flat lines:
//   before   the targeted orders' rate over the recheck's `before` window
//   after    the same orders over the `after` window
//   control  the store's other orders over the `after` window (if any)
// Bars are the whole store; the lines are the orders the action targeted, which
// the legend and the note under the chart say.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports + chart size
// ═══════════════════════════════════════════════════════════════════
import { formatDay, formatRate, formatTarget } from '../../api/format';
import { chartDays, latestRanRecheck } from './chartDays';

// The SVG is drawn in these units and scales to the container's width (CSS)
const WIDTH = 640;
const HEIGHT = 180;
const PAD = { top: 10, right: 8, bottom: 24, left: 40 }; // room for axis labels
const PLOT_W = WIDTH - PAD.left - PAD.right;
const PLOT_H = HEIGHT - PAD.top - PAD.bottom;


// ═══════════════════════════════════════════════════════════════════
// 2. Helpers — y-axis scale
// ═══════════════════════════════════════════════════════════════════
// Pick a round tick step for the highest value, then round the top of the
// axis up to it: highest 22.6% → step 5% → axis 0–25%
const tickStep = (max) => {
  if (max <= 0.1) return 0.02;
  if (max <= 0.3) return 0.05;
  return 0.1;
};

// [0, 0.05, 0.1, ...] up to the top of the axis. Math.round avoids float drift
// (0.1 + 0.2 = 0.30000000000000004).
const buildTicks = (top, step) =>
  Array.from({ length: Math.round(top / step) + 1 }, (_, i) => Math.round(i * step * 1000) / 1000);


// ═══════════════════════════════════════════════════════════════════
// 3. DailyRateChart component
// ═══════════════════════════════════════════════════════════════════
// Props:
//   dailyRates       CaseDetail.daily_rates — [{ date: 'YYYY-MM-DD', rate, claims, eligible_orders }]
//                    dates are already store-local, oldest first
//   windowStartDate  first day of the trigger window, 'YYYY-MM-DD' (format.toStoreDate)
//   goalRate         CaseDetail.goal_rate — drawn as the dashed line
//   causeStartedAt   InvestigationResult.cause_started_at, 'YYYY-MM-DD' (store-local), or null.
//                    No line when it is null or outside the chart's days.
//   rechecks         CaseDetail.rechecks — the latest one that ran extends the chart
const DailyRateChart = ({ dailyRates, windowStartDate, goalRate, causeStartedAt = null, rechecks }) => {
  const recheck = latestRanRecheck(rechecks);
  const days = chartDays(dailyRates, recheck);
  const lines = recheck ? recheckLines(recheck) : [];

  // ── 3a. Scale ───────────────────────────────────────────────────
  // rate: null (too few orders that day) counts as 0 for the scale
  const highest = Math.max(goalRate, ...dailyRates.map((d) => d.rate ?? 0), ...lines.map((l) => l.rate));
  const step = tickStep(highest);
  const top = Math.ceil(highest / step) * step;
  const ticks = buildTicks(top, step);

  const barSlot = PLOT_W / days.length; // width each day gets
  const y = (rate) => PAD.top + PLOT_H - (rate / top) * PLOT_H; // rate → SVG y
  const indexOf = Object.fromEntries(days.map((d, i) => [d.date, i]));
  // A window's left and right edge in SVG x; dates outside the axis are clamped
  const xFrom = (date) => PAD.left + (indexOf[date] ?? 0) * barSlot;
  const xTo = (date) => PAD.left + ((indexOf[date] ?? days.length - 1) + 1) * barSlot;
  const futureFrom = dailyRates.length < days.length ? PAD.left + dailyRates.length * barSlot : null;

  // Trigger window: from its first day to the last day of data ('YYYY-MM-DD' compares as text)
  const windowIndex = dailyRates.findIndex((d) => d.date >= windowStartDate);
  // Cause line: the left edge of that day's bar. Label on the left side when the
  // line is in the right part of the chart, so it never runs off the edge.
  const causeIndex = causeStartedAt ? dailyRates.findIndex((d) => d.date === causeStartedAt) : -1;
  const causeX = PAD.left + causeIndex * barSlot;
  const causeLabel = `Likely cause started · ${formatDay(causeStartedAt).replace(/, \d{4}$/, '')}`;
  const labelOnLeft = causeIndex > days.length * 0.6;

  // ── 3b. Render ──────────────────────────────────────────────────
  return (
    <div className='daily-chart'>
      <div className='daily-chart-head'>
        <h3>Daily M&amp;I rate · last {dailyRates.length} days{recheck && ' + recheck'}</h3>
        <div className='chart-legend'>
          <span className='legend-day'>Daily rate</span>
          <span className='legend-window'>Trigger window</span>
          <span className='legend-goal'>Goal {formatRate(goalRate)}</span>
          {causeIndex >= 0 && <span className='legend-cause'>Likely cause started</span>}
          {recheck && <span className='legend-target'>Targeted orders (recheck)</span>}
          {lines.some((l) => l.kind === 'control') && <span className='legend-control'>Other orders</span>}
        </div>
      </div>

      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role='img'
        aria-label={`Daily M&I rate from ${dailyRates[0]?.date} to ${dailyRates.at(-1)?.date}`
          + (recheck ? `, then the recheck through ${recheck.after.end}` : '')}
      >
        {/* ── Trigger window band, behind everything ── */}
        {windowIndex >= 0 && (
          <rect
            className='chart-window-band'
            x={PAD.left + windowIndex * barSlot}
            y={PAD.top}
            width={(dailyRates.length - windowIndex) * barSlot}
            height={PLOT_H}
            rx='4'
          />
        )}

        {/* ── After the last day of data: shaded, labelled ── */}
        {futureFrom != null && (
          <g>
            <rect className='chart-future' x={futureFrom} y={PAD.top} width={WIDTH - PAD.right - futureFrom} height={PLOT_H} />
            <line className='chart-divider' x1={futureFrom} x2={futureFrom} y1={PAD.top} y2={PAD.top + PLOT_H} />
            <text className='chart-label' x={futureFrom + 4} y={PAD.top + 10}>After the fix</text>
          </g>
        )}

        {/* ── Grid lines + y-axis labels ── */}
        {ticks.map((t) => (
          <g key={t}>
            <line className='chart-grid' x1={PAD.left} x2={WIDTH - PAD.right} y1={y(t)} y2={y(t)} />
            <text className='chart-label' x={PAD.left - 6} y={y(t) + 3} textAnchor='end'>
              {Math.round(t * 100)}%
            </text>
          </g>
        ))}

        {/* ── One bar per day — hover shows the numbers (<title>) ── */}
        {days.map((d, i) => {
          const x = PAD.left + i * barSlot;
          const dateLabel = (i % 7 === 0 || i === days.length - 1) && (
            <text className='chart-label' x={x + barSlot / 2} y={HEIGHT - 6} textAnchor='middle'>
              {d.date.slice(5)}
            </text>
          );
          // Past the last day of data: no daily numbers, just the date
          if (d.future) return <g key={d.date}>{dateLabel}</g>;

          const inWindow = d.date >= windowStartDate; // 'YYYY-MM-DD' compares as text

          // rate: null → a faint full-height outline, so "not enough data"
          // never looks like a 0% day (ui-workflow.md display rules)
          const noData = d.rate == null;
          const height = noData ? PLOT_H : PLOT_H - (y(d.rate) - PAD.top);
          let barClass = 'chart-bar';
          if (inWindow) barClass += ' chart-bar-window';
          if (noData) barClass = 'chart-bar-nodata';

          return (
            <g key={d.date}>
              <rect
                className={barClass}
                x={x + 1}
                y={PAD.top + PLOT_H - height}
                width={barSlot - 2}
                height={height}
              >
                <title>
                  {d.date}: {formatRate(d.rate)} ({d.claims} claims / {d.eligible_orders} orders)
                </title>
              </rect>

              {/* A date label every 7 days, plus the last day */}
              {dateLabel}
            </g>
          );
        })}

        {/* ── Goal line, drawn last so it sits on top of the bars ── */}
        <line className='chart-goal' x1={PAD.left} x2={WIDTH - PAD.right} y1={y(goalRate)} y2={y(goalRate)} />

        {/* ── When the agent says the cause started ── */}
        {causeIndex >= 0 && (
          <g>
            <line className='chart-cause' x1={causeX} x2={causeX} y1={PAD.top} y2={PAD.top + PLOT_H} />
            <text
              className='chart-cause-label'
              x={labelOnLeft ? causeX - 5 : causeX + 5}
              y={PAD.top + 9}
              textAnchor={labelOnLeft ? 'end' : 'start'}
            >
              {causeLabel}
            </text>
          </g>
        )}

        {/* ── Recheck averages: one flat line per window, with its rate ── */}
        {lines.map((l) => {
          const x1 = xFrom(l.start);
          const x2 = xTo(l.end);
          return (
            <g key={l.kind}>
              <line className={`chart-recheck chart-recheck-${l.kind}`} x1={x1} x2={x2} y1={y(l.rate)} y2={y(l.rate)}>
                <title>{l.title}</title>
              </line>
              {l.kind !== 'control' && (
                <text className='chart-recheck-label' x={(x1 + x2) / 2} y={y(l.rate) - 4} textAnchor='middle'>
                  {formatRate(l.rate)}
                </text>
              )}
            </g>
          );
        })}
      </svg>

      <p className='chart-note'>
        Hover a bar for that day's numbers. Dashed outlines are days with too few orders to rate.
        {recheck && (
          <>
            {' '}Bars are the whole store. The blue lines are the orders the action targeted
            ({formatTarget(recheck.target)}), averaged over each recheck window; there are no daily
            numbers after the last day of data.
          </>
        )}
      </p>
    </div>
  );
};


// The recheck's windows as lines to draw; a window with no rate is left out
const recheckLines = (recheck) => [
  ['before', recheck.before, 'Targeted orders before the fix'],
  ['after', recheck.after, 'Targeted orders after the fix'],
  ['control', recheck.control, 'Other orders after the fix'],
]
  .filter(([, w]) => w && w.rate != null)
  .map(([kind, w, label]) => ({
    kind,
    start: w.start,
    end: w.end,
    rate: w.rate,
    title: `${label}, ${w.start} – ${w.end}: ${formatRate(w.rate)} (${w.claims} claims / ${w.eligible_orders} orders)`,
  }));


// ═══════════════════════════════════════════════════════════════════
// 4. Export
// ═══════════════════════════════════════════════════════════════════
export default DailyRateChart;
