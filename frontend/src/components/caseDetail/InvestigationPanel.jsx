// [10h] InvestigationPanel — box 3: holds the agent's run (boxes 4–12)
// Which boxes show is decided in one place, getCaseView (caseSteps.js); this
// component only lays them out, as up to three chapters of the case page:
//
//   ② INVESTIGATION / WHAT THE AGENT FOUND ───── INV-… · started by …
//   ┌──────────────────────────────────────────────────────────────────┐
//   │ Start button (4) and/or progress (5)                             │
//   │ The shared spot (one at a time):                                 │
//   │   question (6) · reply (7) · result (8) · error (10)             │
//   └──────────────────────────────────────────────────────────────────┘
//   ③ YOUR DECISION (red while pending) / RECOMMENDED ACTION ─── PROP-…
//   ┌ the recommended action (9) — or, with no run from the agent,     ┐
//   └ the case's saved action                                          ┘
//   ④ DID THE FIX WORK? — the recheck (13), once one exists
//      then, at step 7, Start new investigation; in analyst review, Mark as resolved
//   ⑤ MERCHANT CONVERSATION — this run's questions and replies (6, read-only),
//      folded. While the run is still going they stay inside the run's card
//      instead, next to the reply form.
//   ⑥ HOW THE AGENT GOT THERE ──────────────────── 8 checks · 5 causes
//   ┌ Checks (11)  |  Possible causes (12)                             ┐
//
// Chapter numbers are a CSS counter, so ones that don't show leave no gap.
// A second run also shows the first one, folded, under the title (box 15).
// id='investigation', 'decide', 'recheck' and 'followup' are where the next-action banner jumps.


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
import { selectProposal } from '../../store/proposals/proposalsSelectors';
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
import RecheckPanel from './RecheckPanel';
import CloseCaseButton from './CloseCaseButton';
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
    // Step 4: the merchant's reply shows up live → confirm it, or "no reply" (box 7)
    case 'reply':
      return <MerchantReplyCard investigation={investigation} timeZone={timeZone} />;
    // Result (box 8). The recommended action (box 9) is its own chapter below.
    case 'result':
      return investigation.result ? (
        <ResultPanel result={investigation.result} checks={investigation.checks} hypotheses={investigation.hypotheses} />
      ) : null;
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

  // ── 3c. Which boxes show (caseSteps.js) ──────────────────────────
  const view = getCaseView({ investigation, caseDetail });
  const timeZone = caseDetail?.store?.timezone;
  // The action for chapter 3: this run's recommendation, or the case's saved one
  const decisionId = (view.slot === 'result' && view.showRecommendation && investigation?.result?.proposal_id)
    || (view.slot === 'proposal' && view.proposalId)
    || null;
  // Already loaded by RecommendationReview; only read here for the chapter's title
  const decision = useSelector((state) => (decisionId ? selectProposal(state, decisionId) : null));

  // ── 3d. Loading, or the Agent Service couldn't be reached ─────────
  // Only this panel shows the error; the rest of the case page still works.
  const runChapter = (meta) => (
    <Chapter title={investigation?.result ? 'What the agent found' : 'Investigation'} meta={meta} id='investigation' />
  );
  if (loadStatus === 'loading' || loadStatus === 'idle') {
    return (
      <>
        {runChapter()}
        <section className='investigation-panel'><p>Loading investigation…</p></section>
      </>
    );
  }
  if (loadStatus === 'failed') {
    return (
      <>
        {runChapter()}
        <section className='investigation-panel'>
          <p className='error'>{loadError}</p>
        </section>
      </>
    );
  }

  // ── 3e. Render ───────────────────────────────────────────────────
  // Red only while the analyst still has to decide (pending, or not loaded yet)
  const pending = !decision || decision.status === 'pending';
  const checkCount = investigation?.checks?.length ?? 0;
  const causeCount = investigation?.hypotheses?.length ?? 0;
  const reopened = view.step === '7';

  return (
    <>
      {/* ── Chapter 2: the run — start, progress, question, reply, result, error ── */}
      {runChapter(investigation && (
        <>
          <span className='mono'>{investigation.investigation_id}</span> · started by {investigation.started_by} ·{' '}
          {formatDateTime(investigation.started_at, timeZone)}
        </>
      ))}
      <section className='investigation-panel' data-step={view.step ?? undefined}>
        {/* Second run: the first one, folded (box 15) */}
        {view.showPrevious && <PreviousInvestigation investigation={investigation} timeZone={timeZone} />}

        {/* Start (box 4) and/or progress (box 5) */}
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
        {/* On failure the Start again button sits inside the error box instead;
            at step 7 it sits under the recheck that said the fix didn't work */}
        {view.showStart && view.slot !== 'error' && !reopened && (
          <StartInvestigationButton caseId={caseId} label={view.startLabel} />
        )}
        {view.showProgress && (
          <InvestigationProgress investigation={investigation} pausedFor={view.pausedFor} pollError={pollError} />
        )}

        {/* Questions this run already asked, read-only (box 6): here while the run
            is still going (next to the reply form), their own chapter once it ends */}
        {view.showQuestionHistory && view.showProgress && (
          <QuestionReview mode='history' investigation={investigation} timeZone={timeZone} />
        )}

        {/* The shared spot (boxes 6–8, 10) */}
        <Slot view={view} caseId={caseId} investigation={investigation} timeZone={timeZone} />
      </section>

      {/* ── Chapter 3: the recommended action (box 9) ── */}
      {decisionId && (
        <>
          <Chapter
            title={pending ? 'Your decision' : 'Recommended action'}
            tone={pending ? 'brand' : undefined}
            meta={<span className='mono'>{decisionId}</span>}
            id='decide'
          />
          <RecommendationReview proposalId={decisionId} timeZone={timeZone} />
        </>
      )}

      {/* ── Did the fix work? (box 13) — hides itself until a recheck exists ── */}
      <RecheckPanel caseId={caseId} />

      {/* Step 7 (reopened): start the second run right under the recheck that said
          the fix didn't work; the new run points at that one. Analyst review
          (rejected action, unsure, second fix failed): close the case once handled. */}
      {((view.showStart && reopened) || view.showClose) && (
        <div className='case-followup' id='followup'>
          {view.showStart && reopened && (
            <StartInvestigationButton caseId={caseId} label={view.startLabel} reopenOf={investigation.investigation_id} />
          )}
          {view.showClose && <CloseCaseButton caseId={caseId} />}
        </div>
      )}

      {/* ── Merchant conversation, once the run has ended — nothing if it asked none ── */}
      {view.showQuestionHistory && !view.showProgress && (
        <QuestionReview mode='history' asChapter investigation={investigation} timeZone={timeZone} />
      )}

      {/* ── Checks (box 11) | possible causes (box 12) ── */}
      {view.showTimeline && (
        <>
          <Chapter
            title='How the agent got there'
            meta={`${checkCount} ${checkCount === 1 ? 'check' : 'checks'} · ${causeCount} ${causeCount === 1 ? 'cause' : 'causes'}`}
          />
          <section className='reasoning-card' aria-label='Checks and possible causes'>
            <div className='investigation-columns'>
              <CheckTimeline checks={investigation.checks} hypotheses={investigation.hypotheses} />
              <HypothesisList hypotheses={investigation.hypotheses} />
            </div>
          </section>
        </>
      )}
    </>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 4. Export
// ═══════════════════════════════════════════════════════════════════
export default InvestigationPanel;
