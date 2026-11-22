// [10h] InvestigationPanel — box 3: holds the agent's run (boxes 4–12)
// Which boxes show is decided in one place, getCaseView (caseSteps.js); this
// component only lays them out, in three parts:
//
//   ② INVESTIGATION ─────────────────────────── INV-… · started by …   ← Chapter, above the card
//   ┌──────────────────────────────────────────────────────────────────┐
//   │ 1. Start button (4) and/or progress (5)                          │
//   │ 2. The shared spot (one at a time):                              │
//   │      question (6) · reply (7) · result (8) + action (9) · error (10) │
//   │      or, with no run from the agent, the case's saved action (9)  │
//   │ 3. Checks (11)  |  Possible causes (12)                          │
//   └──────────────────────────────────────────────────────────────────┘
//
// A second run also shows the first one, folded, under the title (box 15).


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useSelector } from 'react-redux';
import {
  selectInvestigation,
  selectInvestigationLoadStatus,
  selectInvestigationLoadError,
  selectPollError,
  selectLostRunId,
} from '../../store/investigations/investigationsSelectors';
import { selectCaseDetail } from '../../store/cases/casesSelectors';
import usePollInvestigation from '../../hooks/usePollInvestigation';
import { formatDateTime } from '../../api/format';
import { getCaseView } from './caseSteps';
import Chapter from '../common/Chapter';
import StartInvestigationButton from './StartInvestigationButton';
import InvestigationProgress from './InvestigationProgress';
import ResultPanel from './ResultPanel';
import RecommendationReview from './RecommendationReview';
import QuestionReview from './QuestionReview';
import MerchantReplyCard from './MerchantReplyCard';
import PreviousInvestigation from './PreviousInvestigation';
import ErrorPanel from './ErrorPanel';
import CheckTimeline from './CheckTimeline';
import HypothesisList from './HypothesisList';


// ═══════════════════════════════════════════════════════════════════
// 2. The shared spot — boxes 6–10, one at a time
// ═══════════════════════════════════════════════════════════════════
const Slot = ({ view, caseId, investigation, timeZone }) => {
  switch (view.slot) {
    // Step 3: review the agent's question (box 6)
    case 'question':
      return <QuestionReview mode='review' investigation={investigation} timeZone={timeZone} />;
    // Step 4: record the merchant's reply, or "no reply" (box 7)
    case 'reply':
      return <MerchantReplyCard investigation={investigation} />;
    // Result (box 8), then the recommended action under it (box 9)
    case 'result': {
      const { result } = investigation;
      if (!result) return null;
      return (
        <>
          <ResultPanel result={result} checks={investigation.checks} hypotheses={investigation.hypotheses} />
          {view.showRecommendation && result.proposal_id && (
            <RecommendationReview proposalId={result.proposal_id} timeZone={timeZone} />
          )}
        </>
      );
    }
    // The agent has no run (it restarted), but Domain still has the case's action
    case 'proposal':
      return view.proposalId ? <RecommendationReview proposalId={view.proposalId} timeZone={timeZone} /> : null;
    case 'error':
      return <ErrorPanel caseId={caseId} investigation={investigation} startLabel={view.startLabel} />;
    default:
      return null;
  }
};


// ═══════════════════════════════════════════════════════════════════
// 3. InvestigationPanel component
// ═══════════════════════════════════════════════════════════════════
// caseId: the case on screen, e.g. "CASE-0001". CaseDetail loads the latest
// investigation (fetchLatestInvestigation); this panel reads and polls it.
const InvestigationPanel = ({ caseId }) => {
  // ── 3a. State from Redux ─────────────────────────────────────────
  const investigation = useSelector((state) => selectInvestigation(state, caseId));
  const caseDetail = useSelector((state) => selectCaseDetail(state, caseId));
  const loadStatus = useSelector(selectInvestigationLoadStatus);
  const loadError = useSelector(selectInvestigationLoadError);
  const pollError = useSelector(selectPollError);
  const lostRunId = useSelector(selectLostRunId);

  // ── 3b. Poll while running — stops by itself on any other status ──
  usePollInvestigation(investigation?.investigation_id, investigation?.status);

  // ── 3c. Loading, or the Agent Service couldn't be reached ─────────
  // Only this panel shows the error; the rest of the case page still works.
  // The chapter title sits above the card; id='investigation' is where the
  // next-action banner jumps (CaseDetail)
  const chapter = (meta) => (
    <Chapter number={2} title='Investigation' meta={meta} id='investigation' />
  );
  if (loadStatus === 'loading' || loadStatus === 'idle') {
    return (
      <>
        {chapter()}
        <section className='investigation-panel'><p>Loading investigation…</p></section>
      </>
    );
  }
  if (loadStatus === 'failed') {
    return (
      <>
        {chapter()}
        <section className='investigation-panel'>
          <p className='error'>{loadError}</p>
        </section>
      </>
    );
  }

  // ── 3d. Which boxes show (caseSteps.js) ──────────────────────────
  const view = getCaseView({ investigation, caseDetail });
  const timeZone = caseDetail?.store?.timezone;

  return (
    <>
    {/* Chapter title + which run this is */}
    {chapter(investigation && (
      <>
        <span className='mono'>{investigation.investigation_id}</span> · started by {investigation.started_by} ·{' '}
        {formatDateTime(investigation.started_at, timeZone)}
      </>
    ))}
    <section className='investigation-panel' data-step={view.step ?? undefined}>

      {/* Second run: the first one, folded (box 15) */}
      {view.showPrevious && <PreviousInvestigation investigation={investigation} />}

      {/* ── Part 1: Start (box 4) and/or progress (box 5) ── */}
      {/* A poll got 404: the agent restarted while this page was open */}
      {view.step === '1' && lostRunId && (
        <p className='error' role='alert'>
          The agent restarted and lost {lostRunId} before it finished. Start the investigation again.
        </p>
      )}
      {view.step === '1' && !lostRunId && (
        <p className='muted'>The agent checks this store's data and looks for the cause of the spike.</p>
      )}
      {view.step === 'no_run' && (
        <p className='muted'>
          The agent no longer has this investigation's checks and result (it may have restarted).
          {view.proposalId ? ' The recommended action is still saved below.' : ''}
        </p>
      )}
      {/* On failure the Start again button sits inside the error box instead */}
      {view.showStart && view.slot !== 'error' && (
        <StartInvestigationButton
          caseId={caseId}
          label={view.startLabel}
          // Step 7 (reopened): the new run points at the one whose fix didn't work
          reopenOf={view.step === '7' ? investigation.investigation_id : null}
        />
      )}
      {view.showProgress && (
        <InvestigationProgress investigation={investigation} pausedFor={view.pausedFor} pollError={pollError} />
      )}

      {/* Questions this run already asked, read-only, until the run ends (box 6) */}
      {view.showQuestionHistory && (
        <QuestionReview mode='history' investigation={investigation} timeZone={timeZone} />
      )}

      {/* ── Part 2: the shared spot (boxes 6–10) ── */}
      <Slot view={view} caseId={caseId} investigation={investigation} timeZone={timeZone} />

      {/* ── Part 3: checks (box 11) | possible causes (box 12) ── */}
      {view.showTimeline && (
        <div className='investigation-columns'>
          <CheckTimeline checks={investigation.checks} hypotheses={investigation.hypotheses} />
          <HypothesisList hypotheses={investigation.hypotheses} />
        </div>
      )}
    </section>
    </>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 4. Export
// ═══════════════════════════════════════════════════════════════════
export default InvestigationPanel;
