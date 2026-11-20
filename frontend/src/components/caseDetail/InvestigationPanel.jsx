// [10h] InvestigationPanel — bottom of the case page; changes as the investigation moves
// It stays on the same page: no investigation → Start button → progress → finished.
//
// What shows per investigation_status (docs/ui-workflow.md "State-to-component map"):
//   no investigation yet     Start button (analysts) · a note (viewers)
//   running                  progress bar, polled every 2 s
//   awaiting_approval        paused — the question review is D-05
//   awaiting_merchant        paused — the reply form is D-05
//   completed / unsure       finished — the result and decision are D-03
//   failed                   error message + Start again (analysts)


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useDispatch, useSelector } from 'react-redux';
import { startInvestigation } from '../../store/investigations/investigationsThunks';
import { selectIsAnalyst } from '../../store/auth/authSelectors';
import {
  selectInvestigation,
  selectInvestigationLoadStatus,
  selectInvestigationLoadError,
  selectStartStatus,
  selectStartError,
  selectPollError,
} from '../../store/investigations/investigationsSelectors';
import usePollInvestigation from '../../hooks/usePollInvestigation';


// ═══════════════════════════════════════════════════════════════════
// 2. StartButton — shared by "never investigated" and "failed"
// ═══════════════════════════════════════════════════════════════════
// Analysts only. The backend answers 403 for a Viewer anyway — hiding the
// button just keeps them from hitting that error.
const StartButton = ({ caseId, label }) => {
  const dispatch = useDispatch();
  const isAnalyst = useSelector(selectIsAnalyst);
  const startStatus = useSelector(selectStartStatus);
  const startError = useSelector(selectStartError);

  if (!isAnalyst) {
    return <p className='muted'>Only LOE analysts can start an investigation.</p>;
  }

  const starting = startStatus === 'loading';

  return (
    <div className='investigation-start'>
      <button type='button' onClick={() => dispatch(startInvestigation(caseId))} disabled={starting}>
        {starting ? 'Starting…' : label}
      </button>
      {startError && <p className='error' role='alert'>{startError}</p>}
    </div>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 3. InvestigationPanel component
// ═══════════════════════════════════════════════════════════════════
// caseId: the case on screen, e.g. "CASE-0001". CaseDetail loads the latest
// investigation (fetchLatestInvestigation); this panel only reads and polls it.
const InvestigationPanel = ({ caseId }) => {
  // ── 3a. Investigation state from Redux ──────────────────────────
  const investigation = useSelector((state) => selectInvestigation(state, caseId));
  const loadStatus = useSelector(selectInvestigationLoadStatus);
  const loadError = useSelector(selectInvestigationLoadError);
  const pollError = useSelector(selectPollError);

  // ── 3b. Poll while running — stops by itself on any other status ──
  usePollInvestigation(investigation?.investigation_id, investigation?.status);

  // ── 3c. Render — one branch per state, see the table at the top ──
  // Step 1: still loading, or the Agent Service couldn't be reached.
  // Only this panel shows the error; the rest of the case page still works.
  if (loadStatus === 'loading' || loadStatus === 'idle') {
    return <section className='investigation-panel'><p>Loading investigation…</p></section>;
  }
  if (loadStatus === 'failed') {
    return (
      <section className='investigation-panel'>
        <h2>Investigation</h2>
        <p className='error'>{loadError}</p>
      </section>
    );
  }

  // Step 2: never investigated → the Start button
  if (!investigation) {
    return (
      <section className='investigation-panel'>
        <h2>Investigation</h2>
        <p className='muted'>The agent checks this store's data and looks for the cause of the spike.</p>
        <StartButton caseId={caseId} label='Start investigation' />
      </section>
    );
  }

  const { status } = investigation;

  // Step 3: running → progress (step_count of max_steps)
  if (status === 'running') {
    return (
      <section className='investigation-panel'>
        <div className='investigation-progress-head'>
          <h2>Investigating…</h2>
          <span className='muted'>step {investigation.step_count} of {investigation.max_steps}</span>
        </div>
        <progress value={investigation.step_count} max={investigation.max_steps} />
        <p className='muted'>Started by {investigation.started_by} · updates every 2 seconds</p>
        {/* A failed poll is retried on the next tick, so this is only a notice */}
        {pollError && <p className='error'>{pollError} Retrying…</p>}
      </section>
    );
  }

  // Step 4: paused for a human — the controls come in D-05
  if (status === 'awaiting_approval' || status === 'awaiting_merchant') {
    return (
      <section className='investigation-panel'>
        <h2>Investigation paused</h2>
        <p>
          {status === 'awaiting_approval'
            ? 'The agent drafted a question for the merchant and is waiting for an analyst to review it.'
            : 'The question was sent. The agent is waiting for the merchant to reply.'}
        </p>
        {/* D-05: QuestionReview / MerchantReplyForm go here */}
      </section>
    );
  }

  // Step 5: failed → the agent's error message + Start again
  if (status === 'failed') {
    return (
      <section className='investigation-panel'>
        <h2>Investigation failed</h2>
        <p className='error'>{investigation.error?.message ?? 'The investigation stopped with an error.'}</p>
        <StartButton caseId={caseId} label='Start again' />
      </section>
    );
  }

  // Step 6: completed / unsure → finished; the result is shown in D-03
  return (
    <section className='investigation-panel'>
      <h2>Investigation finished</h2>
      <p className='muted'>
        {status === 'completed'
          ? 'The agent found a likely cause.'
          : 'The agent could not confirm a cause from the evidence.'}
      </p>
      {/* D-03: ResultPanel / RecommendationReview go here */}
    </section>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 4. Export
// ═══════════════════════════════════════════════════════════════════
export default InvestigationPanel;
