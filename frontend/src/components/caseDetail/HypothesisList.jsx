// [10n] HypothesisList — box 12: the possible causes, and where each stands
//   POS modifier mapping                                   [Supported]
//   The Extra sauce modifier added on Oct 30 is mis-mapped on kitchen tickets.
//   Survived the challenge: orders without the modifier stayed flat.   ← rationale
//   Supports: EV-EVT-000031 · EV-CLM-004410     Against: —
// Supported first, then open, inconclusive, ruled out — the likeliest on top.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import Pill from '../common/Pill';
import { EvidenceLinks } from '../common/EvidenceLink';
import { labelOf, CAUSE_LABELS, HYPOTHESIS_STATUS_LABELS } from '../../api/format';


// ═══════════════════════════════════════════════════════════════════
// 2. Helpers
// ═══════════════════════════════════════════════════════════════════
const STATUS_TONES = { supported: 'ok', open: 'accent', inconclusive: 'warn', ruled_out: 'bad' };
const STATUS_ORDER = { supported: 0, open: 1, inconclusive: 2, ruled_out: 3 };

// Stable sort: equal statuses keep the agent's order
const byStatus = (a, b) => (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9);


// ═══════════════════════════════════════════════════════════════════
// 3. HypothesisList component
// ═══════════════════════════════════════════════════════════════════
// hypotheses: InvestigationView.hypotheses
const HypothesisList = ({ hypotheses = [] }) => (
  <div className='hypothesis-list'>
    <h3>Possible causes <span className='muted'>({hypotheses.length})</span></h3>
    {hypotheses.length === 0 ? (
      <p className='muted'>The agent hasn't listed any causes yet.</p>
    ) : (
      <ul>
        {[...hypotheses].sort(byStatus).map((h) => (
          <li key={h.hypothesis_id} className={`hypothesis hypothesis-${h.status}`}>
            <div className='hypothesis-head'>
              <strong>{labelOf(CAUSE_LABELS, h.cause_category)}</strong>
              <Pill tone={STATUS_TONES[h.status] ?? 'neutral'}>{labelOf(HYPOTHESIS_STATUS_LABELS, h.status)}</Pill>
            </div>
            <p>{h.statement}</p>
            <p className='muted'>{h.rationale}</p>
            <EvidenceLinks label='Supports' ids={h.supporting_evidence_ids} />
            <EvidenceLinks label='Against' ids={h.contradicting_evidence_ids} />
          </li>
        ))}
      </ul>
    )}
  </div>
);


// ═══════════════════════════════════════════════════════════════════
// 4. Export
// ═══════════════════════════════════════════════════════════════════
export default HypothesisList;
