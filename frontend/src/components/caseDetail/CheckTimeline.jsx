// [10m] CheckTimeline — box 11: each check the agent ran, and what it found
//   1  [Test] Cancellation breakdown                      [Not enough data]
//      Check whether out-of-stock cancellations overlap the claim rise.   ← purpose
//      item_out_of_stock cancellations ran Oct 24–26 only.                ← headline
//      Evidence: EV-CXL-000045
//      ▸ How it fits each cause                                           ← matched, folded
// Oldest first (contracts.md CheckSummary), numbered so the result can say
// "check 4" (checkNumbers in caseSteps.js gives the same numbers).


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import Pill from '../common/Pill';
import { EvidenceLinks } from '../common/EvidenceLink';
import { labelOf, CAUSE_LABELS, CHECK_KIND_LABELS, TOOL_LABELS } from '../../api/format';


// ═══════════════════════════════════════════════════════════════════
// 2. Helpers
// ═══════════════════════════════════════════════════════════════════
// "checks 3, 4" with each number linking to that check in the timeline.
// A check ID the timeline doesn't have (e.g. from the previous run) shows as the raw ID.
export const CheckRefs = ({ ids, numbers }) => {
  if (!ids?.length) return null;
  return (
    <span className='check-refs'>
      {ids.length === 1 ? 'check ' : 'checks '}
      {ids.map((id, i) => (
        <span key={id}>
          {i > 0 && ', '}
          {numbers[id] ? <a href={`#check-${id}`}>{numbers[id]}</a> : id}
        </span>
      ))}
    </span>
  );
};

const KIND_TONES ={ explore: 'neutral', test: 'accent', challenge: 'warn' };

// CheckSummary.matched values → what the analyst reads (ui-workflow.md "Checks")
const MATCH = {
  if_true: { label: 'As predicted', tone: 'ok', side: 'if_true' },
  if_false: { label: 'Against', tone: 'bad', side: 'if_false' },
  neither: { label: 'Neither', tone: 'neutral', side: null },
};

// A hypothesis as a short name: its cause, e.g. "Inventory"
const causeName = (hypothesesById, id) => {
  const h = hypothesesById[id];
  return h ? labelOf(CAUSE_LABELS, h.cause_category) : id;
};


// ═══════════════════════════════════════════════════════════════════
// 3. One check
// ═══════════════════════════════════════════════════════════════════
const CheckItem = ({ check, number, hypothesesById }) => {
  const matches = Object.entries(check.matched ?? {});

  return (
    // id: the result's "check 4" links jump here (CheckRefs)
    <li className='check-item' id={`check-${check.check_id}`}>
      <span className='check-number' aria-hidden='true'>{number}</span>
      <div className='check-body'>
        <div className='check-head'>
          <Pill tone={KIND_TONES[check.kind] ?? 'neutral'}>{labelOf(CHECK_KIND_LABELS, check.kind)}</Pill>
          <strong>{labelOf(TOOL_LABELS, check.tool)}</strong>
          {check.challenges && (
            <span className='muted'>challenges {causeName(hypothesesById, check.challenges)}</span>
          )}
          {check.data_sufficient === false && <Pill tone='warn'>Not enough data</Pill>}
        </div>
        <p>{check.purpose}</p>
        <p className='check-headline'>{check.headline}</p>
        {/* A check can cite dozens of records: first 3, the rest folded */}
        <EvidenceLinks label='Evidence' ids={check.evidence_ids} limit={3} />

        {/* Per cause: did the result match what the agent expected if it were true? */}
        {matches.length > 0 && (
          <details className='check-matched'>
            <summary>How it fits each cause</summary>
            <ul>
              {matches.map(([hypothesisId, value]) => {
                const m = MATCH[value] ?? MATCH.neither;
                const expectation = check.expectations?.find((e) => e.hypothesis_id === hypothesisId);
                return (
                  <li key={hypothesisId}>
                    <Pill tone={m.tone}>{m.label}</Pill> <strong>{causeName(hypothesesById, hypothesisId)}</strong>
                    {expectation && m.side && <span className='muted'> — expected “{expectation[m.side]}”</span>}
                  </li>
                );
              })}
            </ul>
          </details>
        )}
      </div>
    </li>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 4. CheckTimeline component
// ═══════════════════════════════════════════════════════════════════
// checks: InvestigationView.checks (oldest first) · hypotheses: for cause names
const CheckTimeline = ({ checks = [], hypotheses = [] }) => {
  const hypothesesById = Object.fromEntries(hypotheses.map((h) => [h.hypothesis_id, h]));

  return (
    <div className='check-timeline'>
      <h3>Checks <span className='muted'>({checks.length})</span></h3>
      {checks.length === 0 ? (
        <p className='muted'>No checks yet.</p>
      ) : (
        <ol>
          {checks.map((check, i) => (
            <CheckItem key={check.check_id} check={check} number={i + 1} hypothesesById={hypothesesById} />
          ))}
        </ol>
      )}
    </div>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 5. Export
// ═══════════════════════════════════════════════════════════════════
export default CheckTimeline;
