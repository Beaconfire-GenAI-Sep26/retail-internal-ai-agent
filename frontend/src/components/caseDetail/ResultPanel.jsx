// [10o] ResultPanel — box 8: the agent's conclusion
// Two layouts, by InvestigationResult.outcome (ui-workflow.md v0.3 "Result and causes"):
//
//   diagnosis                                    unsure
//   Likely cause: POS modifier mapping [High]    No cause confirmed [Low]
//   Since Oct 30, 2026                           summary
//   summary                                      Couldn't check: the evidence gaps
//   Supporting / contradicting evidence          Ruled out
//   Survived challenge: check 5                  8 checks tried · sent to analyst review
//   Ruled out: cause — reason · evidence · checks
//   Couldn't check
//   Merchant said, not verified
//
// The recommended action (box 9, RecommendationReview) sits under this panel from commit 3.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import Pill from '../common/Pill';
import { EvidenceLinks } from '../common/EvidenceLink';
import { CheckRefs } from './CheckTimeline';
import { checkNumbers } from './caseSteps';
import { formatDay, labelOf, CAUSE_LABELS, CONFIDENCE_LABELS } from '../../api/format';


// ═══════════════════════════════════════════════════════════════════
// 2. Pieces shared by both layouts
// ═══════════════════════════════════════════════════════════════════
const CONFIDENCE_TONES = { high: 'ok', medium: 'accent', low: 'warn' };

const ConfidencePill = ({ confidence }) => (
  <Pill tone={CONFIDENCE_TONES[confidence] ?? 'neutral'}>{labelOf(CONFIDENCE_LABELS, confidence)}</Pill>
);

// A titled list; nothing when the list is empty
const Section = ({ title, items, render = (x) => x, className }) => {
  if (!items?.length) return null;
  return (
    <div className={`result-section ${className ?? ''}`}>
      <h4>{title}</h4>
      <ul>{items.map((item, i) => <li key={i}>{render(item)}</li>)}</ul>
    </div>
  );
};

// ruled_out[] — each cause the agent excluded, with its proof (records, checks or both)
const RuledOut = ({ items, numbers }) => (
  <Section
    title='Ruled out'
    items={items}
    render={(r) => (
      <>
        <strong>{labelOf(CAUSE_LABELS, r.cause_category)}</strong> — {r.reason}{' '}
        <span className='muted'><CheckRefs ids={r.check_ids} numbers={numbers} /></span>
        <EvidenceLinks ids={r.evidence_ids} />
      </>
    )}
  />
);


// ═══════════════════════════════════════════════════════════════════
// 3. ResultPanel component
// ═══════════════════════════════════════════════════════════════════
// result: InvestigationResult · checks: InvestigationView.checks, for "check 4" links
const ResultPanel = ({ result, checks = [] }) => {
  const numbers = checkNumbers(checks);

  // ── 3a. Unsure: no cause confirmed, what was missing, sent to a person ──
  if (result.outcome === 'unsure') {
    return (
      <div className='result-panel result-unsure'>
        <div className='result-head'>
          <h3>No cause confirmed</h3>
          <ConfidencePill confidence={result.confidence} />
        </div>
        <p>{result.summary}</p>
        <Section title="Couldn't check" items={result.evidence_gaps} className='result-gaps' />
        <RuledOut items={result.ruled_out} numbers={numbers} />
        <Section title='Merchant said, not verified' items={result.unverified_reply_claims} />
        <p className='muted'>
          {result.checks_tried?.length ?? 0} checks tried · The case went to analyst review.
        </p>
      </div>
    );
  }

  // ── 3b. Diagnosis: the cause, how sure, since when, and the proof ──
  return (
    <div className='result-panel'>
      <div className='result-head'>
        <h3>Likely cause: {labelOf(CAUSE_LABELS, result.cause_category)}</h3>
        <ConfidencePill confidence={result.confidence} />
      </div>
      {result.cause_started_at && <p className='muted'>Since {formatDay(result.cause_started_at)}</p>}
      <p>{result.summary}</p>

      <EvidenceLinks label='Supporting evidence' ids={result.supporting_evidence_ids} />
      <EvidenceLinks label='Contradicting evidence' ids={result.contradicting_evidence_ids} />
      {result.challenge_check_ids?.length > 0 && (
        <p className='muted'>
          Survived a challenge: <CheckRefs ids={result.challenge_check_ids} numbers={numbers} />
        </p>
      )}

      <RuledOut items={result.ruled_out} numbers={numbers} />
      <Section title="Couldn't check" items={result.evidence_gaps} />
      <Section title='Merchant said, not verified' items={result.unverified_reply_claims} />
    </div>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 4. Export
// ═══════════════════════════════════════════════════════════════════
export default ResultPanel;
