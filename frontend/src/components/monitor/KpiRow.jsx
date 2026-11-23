// [14d] KpiRow — four headline numbers for the chosen range (D-06)
//   M&I rate · delivered orders · attributable claims · cancellation rate
// One store: a big number. Several stores: one line per store with its color dot.
// Each value shows its change from the previous period of the same length; an
// arrow is red when the change is bad (a rate going up), green when good.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports + the four KPIs
// ═══════════════════════════════════════════════════════════════════
import { formatRate } from '../../api/format';
import { delta } from './monitorMath';

const count = (n) => (n == null ? '—' : n.toLocaleString('en-US'));

// get: (stats) → value · kind: how the change is measured · badUp: up is bad?
const KPIS = [
  { key: 'rate', label: 'M&I rate', get: (s) => s.claims.rate, format: formatRate, kind: 'pt', badUp: true },
  { key: 'orders', label: 'Delivered orders', get: (s) => s.claims.den, format: count, kind: 'pct', badUp: null },
  { key: 'claims', label: 'Attributable claims', get: (s) => s.claims.num, format: count, kind: 'pct', badUp: true },
  { key: 'cancel', label: 'Cancellation rate', get: (s) => s.cancels.rate, format: formatRate, kind: 'pt', badUp: true },
];


// ═══════════════════════════════════════════════════════════════════
// 2. Delta — "▲ 2.1pt", colored by whether the change is good
// ═══════════════════════════════════════════════════════════════════
const Delta = ({ kpi, current, previous }) => {
  if (!previous) return null;
  const d = delta(kpi.get(current), kpi.get(previous), kpi.kind);
  if (!d) return null;
  // Judged on the shown text, so a change that rounds to "0%" / "0.0pt" reads as none
  if (parseFloat(d.text) === 0) return <span className='kpi-delta'>no change</span>;
  const up = d.diff > 0;
  const tone = kpi.badUp == null ? '' : up === kpi.badUp ? ' kpi-delta-bad' : ' kpi-delta-good';
  return (
    <span className={`kpi-delta${tone}`}>
      <span aria-hidden='true'>{up ? '▲' : '▼'}</span> {up ? 'up' : 'down'} {d.text}
    </span>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 3. KpiRow component
// ═══════════════════════════════════════════════════════════════════
// Props:
//   stores   [{ storeId, color, current, previous, pendingClaims }]
//            current / previous: { claims: {num, den, rate}, cancels: {num, den, rate} }
//            previous is null when the range has no earlier period (42 days)
//   days     length of the range, for "vs previous 14 days"
//   goal     goal rate, under the M&I rate
const KpiRow = ({ stores, days, goal }) => {
  const compared = stores.some((s) => s.previous);
  const footOf = (kpi) => {
    const parts = [];
    if (kpi.key === 'rate') parts.push(`goal ${formatRate(goal)}`);
    if (kpi.key === 'claims') parts.push(`${stores.map((s) => s.pendingClaims ?? '—').join(' / ')} pending review`);
    if (compared) parts.push(`vs previous ${days} days`);
    return parts.join(' · ');
  };

  return (
    <div className='kpi-row'>
      {KPIS.map((kpi) => (
        <div key={kpi.key} className='kpi-card'>
          <span className='stat-label'>{kpi.label}</span>
          {stores.length === 1 ? (
            <>
              <span className='kpi-big'>{kpi.format(kpi.get(stores[0].current))}</span>
              <Delta kpi={kpi} current={stores[0].current} previous={stores[0].previous} />
            </>
          ) : (
            stores.map((s) => (
              <div key={s.storeId} className='kpi-line'>
                <span className='swatch' style={{ background: s.color }} aria-label={s.storeId} />
                <span className='kpi-value'>{kpi.format(kpi.get(s.current))}</span>
                <Delta kpi={kpi} current={s.current} previous={s.previous} />
              </div>
            ))
          )}
          <span className='kpi-foot'>{footOf(kpi)}</span>
        </div>
      ))}
    </div>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 4. Export
// ═══════════════════════════════════════════════════════════════════
export default KpiRow;
