// [10o] ResultPanel — box 8: the agent's conclusion
// Two layouts, by InvestigationResult.outcome (ui-workflow.md v0.3 "Result and causes"):
//
//   diagnosis                                        unsure
//   ✦ Agent diagnosis                                ✦ Agent result
//   LIKELY CAUSE · SINCE OCT 30, 2026   [High] ▮▮▮   NO CAUSE CONFIRMED          [Low] ▮▯▯
//   POS modifier mapping                ← the verdict, largest text in the card
//   summary                                          summary
//   ┌ Supporting  EV-… EV-…                ┐        8 checks tried · sent to analyst review
//   │ Contradicting  None found            │
//   └ ✓ Held up against a challenge: check 5┘
//   ┌ Ruled out ┐ ┌ Couldn't check ┐ ┌ Merchant said, not verified ┐   ← side by side,
//   └───────────┘ └────────────────┘ └─────────────────────────────┘     empty ones hidden
//
// Purple marks the agent's words (vs store facts and people). Grey = ruled out,
// amber = couldn't check, purple = merchant's words the agent didn't verify.
// The recommended action (box 9) is its own chapter under this one (InvestigationPanel).


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import Pill from '../common/Pill';
import { EvidenceLinks } from '../common/EvidenceLink';
import { CheckRefs } from './CheckTimeline';
import { checkNumbers, survivedChallenges } from './caseSteps';
import { formatDay, labelOf, CAUSE_LABELS, CONFIDENCE_LABELS } from '../../api/format';


// ═══════════════════════════════════════════════════════════════════
// 2. Pieces shared by both layouts
// ═══════════════════════════════════════════════════════════════════
const CONFIDENCE_TONES = { high: 'ok', medium: 'accent', low: 'warn' };
const CONFIDENCE_BARS = { high: 3, medium: 2, low: 1 };

// "High confidence" + 3 small bars, filled by level
const Confidence = ({ confidence }) => {
  const tone = CONFIDENCE_TONES[confidence] ?? 'neutral';
  const filled = CONFIDENCE_BARS[confidence] ?? 0;
  return (
    <div className='confidence'>
      <Pill tone={tone}>{labelOf(CONFIDENCE_LABELS, confidence)}</Pill>
      <span className={`confidence-bars confidence-${tone}`} aria-hidden='true'>
        {[1, 2, 3].map((n) => <i key={n} className={n <= filled ? 'on' : undefined} />)}
      </span>
    </div>
  );
};

// ✦ Agent diagnosis — the purple tag on top of anything the agent concluded
const AgentTag = ({ children }) => (
  <span className='agent-tag'>
    <svg viewBox='0 0 24 24' aria-hidden='true' fill='currentColor'>
      <path d='M12 2l2.2 6.3L20 10l-5.8 1.7L12 18l-2.2-6.3L4 10l5.8-1.7z' />
    </svg>
    {children}
  </span>
);

// One box of the side-by-side row; nothing when the list is empty
//   tone: 'out' (ruled out, grey) · 'gap' (couldn't check, amber) · 'said' (merchant, purple)
const Side = ({ title, tone, items, render = (x) => x }) => {
  if (!items?.length) return null;
  return (
    <div className={`result-side result-side-${tone}`}>
      <h4>{title}</h4>
      <ul>{items.map((item, i) => <li key={i}>{render(item)}</li>)}</ul>
    </div>
  );
};

// ruled_out[] — each cause the agent excluded, with its proof (records, checks or both)
const ruledOutItem = (numbers) => (r) => (
  <>
    <strong>{labelOf(CAUSE_LABELS, r.cause_category)}</strong> — {r.reason}{' '}
    <span className='muted'><CheckRefs ids={r.check_ids} numbers={numbers} /></span>
    <EvidenceLinks ids={r.evidence_ids} />
  </>
);

// The row of side boxes, in the order the analyst reads them
const Sides = ({ result, numbers, gapsFirst = false }) => {
  const ruledOut = <Side key='out' title='Ruled out' tone='out' items={result.ruled_out} render={ruledOutItem(numbers)} />;
  const gaps = <Side key='gap' title="Couldn't check" tone='gap' items={result.evidence_gaps} />;
  const said = (
    <Side key='said' title='Merchant said, not verified' tone='said'
      items={result.unverified_reply_claims} render={(text) => <q>{text}</q>} />
  );
  const boxes = gapsFirst ? [gaps, ruledOut, said] : [ruledOut, gaps, said];
  const any = result.ruled_out?.length || result.evidence_gaps?.length || result.unverified_reply_claims?.length;
  return any ? <div className='result-sides'>{boxes}</div> : null;
};


// ═══════════════════════════════════════════════════════════════════
// 3. ResultPanel component
// ═══════════════════════════════════════════════════════════════════
// result: InvestigationResult · checks: InvestigationView.checks, for "check 4" links
// hypotheses: InvestigationView.hypotheses, to tell which cause a challenge tested
const ResultPanel = ({ result, checks = [], hypotheses = [] }) => {
  const numbers = checkNumbers(checks);

  // ── 3a. Unsure: no cause confirmed, what was missing, sent to a person ──
  if (result.outcome === 'unsure') {
    return (
      <div className='result-panel result-unsure'>
        <AgentTag>Agent result</AgentTag>
        <div className='result-verdict'>
          <div>
            <span className='eyebrow'>Outcome</span>
            <h3>No cause confirmed</h3>
          </div>
          <Confidence confidence={result.confidence} />
        </div>
        <p className='result-summary'>{result.summary}</p>
        {/* What was missing is the main point here, so it comes first */}
        <Sides result={result} numbers={numbers} gapsFirst />
        <p className='result-foot'>
          {result.checks_tried?.length ?? 0} checks tried · The case went to analyst review.
        </p>
      </div>
    );
  }

  // ── 3b. Diagnosis: the cause, how sure, since when, and the proof ──
  const survived = survivedChallenges(result, checks, hypotheses);
  const since = result.cause_started_at ? ` · since ${formatDay(result.cause_started_at)}` : '';
  return (
    <div className='result-panel'>
      <AgentTag>Agent diagnosis</AgentTag>
      <div className='result-verdict'>
        <div>
          <span className='eyebrow'>Likely cause{since}</span>
          <h3>{labelOf(CAUSE_LABELS, result.cause_category)}</h3>
        </div>
        <Confidence confidence={result.confidence} />
      </div>
      <p className='result-summary'>{result.summary}</p>

      {/* The proof, in one tinted block */}
      <div className='result-proof'>
        <EvidenceLinks label='Supporting' ids={result.supporting_evidence_ids} tone='support' />
        {result.contradicting_evidence_ids?.length ? (
          <EvidenceLinks label='Contradicting' ids={result.contradicting_evidence_ids} tone='against' />
        ) : (
          <p className='evidence-links'><span className='muted'>Contradicting: </span>None found</p>
        )}
        {/* Only the challenges the cause held up against, not every one tried */}
        {survived.length > 0 && (
          <p className='result-held'>
            <svg viewBox='0 0 24 24' aria-hidden='true' fill='none' stroke='currentColor' strokeWidth='2.6'
              strokeLinecap='round' strokeLinejoin='round'>
              <path d='M20 6L9 17l-5-5' />
            </svg>
            Held up against a challenge: <CheckRefs ids={survived} numbers={numbers} />
          </p>
        )}
      </div>

      <Sides result={result} numbers={numbers} />
    </div>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 4. Export
// ═══════════════════════════════════════════════════════════════════
export default ResultPanel;
