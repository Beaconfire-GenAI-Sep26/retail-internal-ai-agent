// [10z] CaseStepper — where the case is, as 5 stages under the header
//   ━━━━━━━━━━  ━━━━━━━━━━  ━━━━━━━━━━  ──────────  ──────────
//   Detected    Investigated Decide action Action sent Recheck
//   Nov 15      8 checks     Waiting on you —          14 days after sent
// done = black bar · current = red bar if the analyst has to act, purple otherwise
// · not yet = grey. The stages come from caseStages.js (no API call).


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { getCaseStages } from './caseStages';


// ═══════════════════════════════════════════════════════════════════
// 2. CaseStepper component
// ═══════════════════════════════════════════════════════════════════
// view: getCaseView(...), or null when the investigation isn't loaded
const CaseStepper = ({ view, investigation, caseDetail }) => {
  const stages = getCaseStages({ view, investigation, caseDetail });
  return (
    <ol className='case-stepper' aria-label='Case progress'>
      {stages.map((s) => (
        <li
          key={s.key}
          className={`stage stage-${s.state}${s.attention ? ' stage-attention' : ''}`}
          aria-current={s.state === 'now' ? 'step' : undefined}
        >
          <span className='stage-label'>{s.label}</span>
          <span className='stage-note'>{s.note}</span>
        </li>
      ))}
    </ol>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default CaseStepper;
