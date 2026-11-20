// [10g] DailyRateChart — the case "history": one bar per day for 42 days
// Plain SVG, no chart library. Bars inside the trigger window are highlighted,
// and a dashed line marks the goal, so the analyst sees when the rate jumped.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports + chart size
// ═══════════════════════════════════════════════════════════════════
import { formatRate } from '../../api/format';

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
const DailyRateChart = ({ dailyRates, windowStartDate, goalRate }) => {
  // ── 3a. Scale ───────────────────────────────────────────────────
  // rate: null (too few orders that day) counts as 0 for the scale
  const highest = Math.max(goalRate, ...dailyRates.map((d) => d.rate ?? 0));
  const step = tickStep(highest);
  const top = Math.ceil(highest / step) * step;
  const ticks = buildTicks(top, step);

  const barSlot = PLOT_W / dailyRates.length; // width each day gets
  const y = (rate) => PAD.top + PLOT_H - (rate / top) * PLOT_H; // rate → SVG y

  // ── 3b. Render ──────────────────────────────────────────────────
  return (
    <section className='daily-chart'>
      <div className='daily-chart-head'>
        <h2>Daily M&amp;I rate · last {dailyRates.length} days</h2>
        <div className='chart-legend'>
          <span className='legend-day'>Daily rate</span>
          <span className='legend-window'>Trigger window</span>
          <span className='legend-goal'>Goal {formatRate(goalRate)}</span>
        </div>
      </div>

      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role='img'
        aria-label={`Daily M&I rate from ${dailyRates[0]?.date} to ${dailyRates.at(-1)?.date}`}
      >
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
        {dailyRates.map((d, i) => {
          const x = PAD.left + i * barSlot;
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
              {(i % 7 === 0 || i === dailyRates.length - 1) && (
                <text className='chart-label' x={x + barSlot / 2} y={HEIGHT - 6} textAnchor='middle'>
                  {d.date.slice(5)}
                </text>
              )}
            </g>
          );
        })}

        {/* ── Goal line, drawn last so it sits on top of the bars ── */}
        <line className='chart-goal' x1={PAD.left} x2={WIDTH - PAD.right} y1={y(goalRate)} y2={y(goalRate)} />
      </svg>

      <p className='muted'>Hover a bar for that day's numbers. Dashed outlines are days with too few orders to rate.</p>
    </section>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 4. Export
// ═══════════════════════════════════════════════════════════════════
export default DailyRateChart;
