// [10l] InvestigationProgress — box 5: how far the agent is, and what it checks now
//   Investigating…                         4 checks done (max 12)
//   ████████░░░░░░░░░░░░░░░░
//   Now: Check whether out-of-stock cancellations overlap the claim rise.
// Paused (steps 3, 4): the bar stops and says who the agent is waiting for.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import Pill from '../common/Pill';


// ═══════════════════════════════════════════════════════════════════
// 2. InvestigationProgress component
// ═══════════════════════════════════════════════════════════════════
// investigation: InvestigationView · pausedFor: null | 'analyst' | 'merchant' (getCaseView)
// pollError: last poll failed (polling keeps trying)
const InvestigationProgress = ({ investigation, pausedFor, pollError }) => {
  const { step_count: done, max_steps: max, checks = [] } = investigation;
  const latest = checks[checks.length - 1];

  return (
    <div className='investigation-progress'>
      <div className='investigation-progress-head'>
        <h2>
          {pausedFor ? 'Investigation paused' : 'Investigating…'}{' '}
          {pausedFor === 'analyst' && <Pill tone='warn'>Waiting for you</Pill>}
          {pausedFor === 'merchant' && <Pill tone='warn'>Waiting for the merchant</Pill>}
        </h2>
        <span className='muted'>{done} {done === 1 ? 'check' : 'checks'} done (max {max})</span>
      </div>
      <progress value={done} max={max} aria-label={`${done} of at most ${max} checks done`} />

      {/* What the agent is doing — the newest check's purpose */}
      {!pausedFor && (
        <p className='muted'>
          {latest ? <>Now: {latest.purpose}</> : 'Loading the case and the store data…'}
        </p>
      )}
      {pausedFor === 'analyst' && (
        <p className='muted'>The agent drafted a question for the merchant. It continues after an analyst reviews it.</p>
      )}
      {pausedFor === 'merchant' && (
        <p className='muted'>The question was sent. The agent continues after the reply, or "no reply", is recorded.</p>
      )}

      {/* A failed poll is retried on the next tick, so this is only a notice */}
      {pollError && <p className='error'>{pollError} Retrying…</p>}
    </div>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default InvestigationProgress;
