// [10f2] CaseKpis — the three numbers behind the case, chapter 1 of the page
//   ┌ M&I RATE · TRIGGER WINDOW ──┐ ┌ BASELINE ───────┐ ┌ GOAL ──────────┐
//   │ 4.8%  ▲ 2.9 pts vs baseline │ │ 1.9%            │ │ 3.0%           │
//   │ 29 / 604 claims / orders    │ │ prior 28 days   │ │ above opens a  │
//   │ ●───|────|────────○────     │ └─────────────────┘ └────────────────┘
//   └─────────────────────────────┘
// Only the rate that triggered the case is red. The bar under it places the
// rate against the baseline and the goal (green → amber → red zones).


// ═══════════════════════════════════════════════════════════════════
// 1. Imports + helpers
// ═══════════════════════════════════════════════════════════════════
import { formatRate, formatRatio } from '../../api/format';

// 0.048 vs 0.019 → "▲ 2.9 pts vs baseline"
const pointsVsBaseline = (rate, baseline) => {
  const points = (rate - baseline) * 100;
  const arrow = points >= 0 ? '▲' : '▼';
  return `${arrow} ${Math.abs(points).toFixed(1)} pts vs baseline`;
};

// Top of the bar: 25% above the highest of the three, rounded up to a whole percent
const barTop = (...rates) => Math.ceil(Math.max(...rates) * 1.25 * 100) / 100 || 0.01;

// A rate → its position on the bar, as a CSS percentage
const pos = (rate, top) => `${Math.min(100, (rate / top) * 100)}%`;


// ═══════════════════════════════════════════════════════════════════
// 2. CaseKpis component
// ═══════════════════════════════════════════════════════════════════
// caseDetail: CaseDetail (mi_rate, baseline_rate, goal_rate, claims / orders)
const CaseKpis = ({ caseDetail }) => {
  const { mi_rate: rate, baseline_rate: baseline, goal_rate: goal } = caseDetail;
  const top = barTop(rate, baseline, goal);

  return (
    <div className='case-kpis'>
      <div className='case-kpi case-kpi-alert'>
        <span className='eyebrow'>M&amp;I rate · trigger window</span>
        <span className='case-kpi-value'>
          {formatRate(rate)}
          <span className='case-kpi-delta'>{pointsVsBaseline(rate, baseline)}</span>
        </span>
        <span className='case-kpi-foot'>
          {formatRatio(caseDetail.attributable_claims, caseDetail.eligible_orders)} claims / orders
        </span>
        {/* Decorative: every number on it is written out in the cards */}
        <div
          className='rate-bar'
          aria-hidden='true'
          style={{ '--baseline': pos(baseline, top), '--goal': pos(goal, top) }}
        >
          <i className='rate-bar-baseline' />
          <i className='rate-bar-goal' />
          <span className='rate-bar-value' style={{ left: pos(rate, top) }} />
        </div>
        <div className='rate-bar-labels' aria-hidden='true'>
          <span>0%</span>
          <span>{formatRate(top).replace('.0%', '%')}</span>
        </div>
      </div>

      <div className='case-kpi'>
        <span className='eyebrow'>Baseline</span>
        <span className='case-kpi-value'>{formatRate(baseline)}</span>
        <span className='case-kpi-foot'>The store's usual level, prior 28 days</span>
      </div>

      <div className='case-kpi'>
        <span className='eyebrow'>Goal</span>
        <span className='case-kpi-value'>{formatRate(goal)}</span>
        <span className='case-kpi-foot'>Above this opens a case</span>
      </div>
    </div>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default CaseKpis;
