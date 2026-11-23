// [14c] BarList — grouped horizontal bars, one bar per store in each row (D-06)
// Used by three cards: error categories, M&I rate by daypart, cancellation reasons.
// Bars are square at the baseline with a 4px rounded end; the value is written
// at the end of each bar, and the native <title> gives the details on hover.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports + layout
// ═══════════════════════════════════════════════════════════════════
import useElementWidth from '../../hooks/useElementWidth';

const GAP = 2; // between the bars of one row
const ROW_GAP = 14;
const VALUE_W = 60; // room for the value text after the longest bar


// ═══════════════════════════════════════════════════════════════════
// 2. BarList component
// ═══════════════════════════════════════════════════════════════════
// Props:
//   rows      [{ key, label, bars: [{ storeId, color, value, text, title }] }]
//             value is the bar length (count or rate); text is what is written
//   labelW    width of the row labels (px)
//   refValue  optional reference drawn as a dashed line (the goal rate); its
//             legend entry lives in the card
//   flagOver  with refValue: bars above it are brand red (var(--chart-over)),
//             the rest keep the store color. The value is written on every bar,
//             and the card's legend names the red, so it isn't color alone.
//   min       axis maximum is at least this
const BarList = ({ rows, labelW = 110, refValue = null, flagOver = false, min = 0 }) => {
  const [ref, width] = useElementWidth(400);
  const perRow = rows[0]?.bars.length ?? 1;
  const barH = perRow > 1 ? 12 : 16;
  const rowH = perRow * barH + (perRow - 1) * GAP;
  const height = rows.length * (rowH + ROW_GAP) + 4;
  const plotW = Math.max(20, width - labelW - VALUE_W);
  const max = Math.max(min, refValue ?? 0, ...rows.flatMap((r) => r.bars.map((b) => b.value ?? 0))) || 1;
  const len = (v) => ((v ?? 0) / max) * plotW;

  // Bar path: square at the baseline, rounded data end
  const barPath = (x0, y0, w) => {
    const r = Math.min(4, w / 2, barH / 2);
    return `M${x0},${y0}H${x0 + w - r}Q${x0 + w},${y0} ${x0 + w},${y0 + r}V${y0 + barH - r}Q${x0 + w},${y0 + barH} ${x0 + w - r},${y0 + barH}H${x0}Z`;
  };

  return (
    <div className='bar-list' ref={ref}>
      <svg width={width} height={height} role='img' aria-label={rows.map((r) => `${r.label}: ${r.bars.map((b) => `${b.storeId} ${b.text}`).join(', ')}`).join('; ')}>
        <line x1={labelW} x2={labelW} y1='0' y2={height - 4} className='chart-axis' />
        {refValue != null && (
          <line x1={labelW + len(refValue)} x2={labelW + len(refValue)} y1='0' y2={height - 4} className='chart-goal' />
        )}
        {rows.map((row, ri) => {
          const y0 = 2 + ri * (rowH + ROW_GAP);
          return (
            <g key={row.key}>
              <text x={labelW - 8} y={y0 + rowH / 2 + 4} textAnchor='end' className='bar-label'>{row.label}</text>
              {row.bars.map((b, k) => {
                const by = y0 + k * (barH + GAP);
                const w = b.value ? Math.max(3, len(b.value)) : 0;
                return (
                  <g key={b.storeId}>
                    <title>{b.title}</title>
                    <rect x={labelW} y={by - 1} width={plotW + VALUE_W} height={barH + 2} fill='transparent' />
                    {w > 0 && (
                      <path
                        d={barPath(labelW, by, w)}
                        fill={flagOver && refValue != null && b.value > refValue ? 'var(--chart-over)' : b.color}
                      />
                    )}
                    <text x={labelW + w + 6} y={by + barH / 2 + 4} className='chart-label'>{b.text}</text>
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>
    </div>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default BarList;
