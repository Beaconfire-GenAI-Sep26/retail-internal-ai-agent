// [08d] usePollInvestigation — refresh a running investigation every 2 s
// The agent works in the background, so the UI asks for its progress
// (contracts.md "Agent Service": "the frontend polls every 2 seconds").


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useEffect } from 'react';
import { useDispatch } from 'react-redux';
import { fetchInvestigation } from '../store/investigations/investigationsThunks';

const POLL_INTERVAL_MS = 2000;


// ═══════════════════════════════════════════════════════════════════
// 2. Hook
// ═══════════════════════════════════════════════════════════════════
// Polls only while status is 'running'. Every other status stops it:
//   awaiting_approval / awaiting_merchant → paused until an analyst acts (D-05)
//   completed / unsure / failed           → finished
// Each poll stores the new status, which re-runs this effect, so polling stops
// on its own as soon as the status changes. Leaving the page stops it too
// (the effect's cleanup).
// Usage: usePollInvestigation(investigation?.investigation_id, investigation?.status)
const usePollInvestigation = (investigationId, status) => {
  const dispatch = useDispatch();

  useEffect(() => {
    if (!investigationId || status !== 'running') return;

    const timer = setInterval(() => {
      dispatch(fetchInvestigation(investigationId));
    }, POLL_INTERVAL_MS);

    return () => clearInterval(timer);
  }, [dispatch, investigationId, status]);
};


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default usePollInvestigation;
