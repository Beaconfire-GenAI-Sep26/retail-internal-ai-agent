// [08g] usePollMerchantReply — watch Domain for the merchant's answer (D-05)
// Step 4 (awaiting_merchant). The merchant's answer reaches Domain by itself,
// at any time after the question is dispatched. The run stays paused until an
// analyst confirms it, so the agent can't tell the UI a reply came in — the
// card asks Domain directly:
//   GET /domain/cases/{case_id}/merchant-replies   every 3 s
// while `active` (paused for the merchant, and this question has no reply yet).
// Once the reply is in the store, the caller passes active=false and polling stops.
// Also refetches when the tab regains focus, like usePollInvestigation.
//
// Usage: usePollMerchantReply(investigation.case_id, !reply)


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useEffect } from 'react';
import { useDispatch } from 'react-redux';
import { fetchMerchantReplies } from '../store/proposals/proposalsThunks';

export const REPLY_POLL_INTERVAL_MS = 3000;


// ═══════════════════════════════════════════════════════════════════
// 2. Hook
// ═══════════════════════════════════════════════════════════════════
// One read right away (also covers a reply that was already there on load),
// then one every REPLY_POLL_INTERVAL_MS. fetchMerchantReplies skips a call
// while the previous one is still loading, so a slow Domain never stacks requests.
const usePollMerchantReply = (caseId, active) => {
  const dispatch = useDispatch();

  useEffect(() => {
    if (!caseId || !active) return;

    const check = () => {
      if (document.visibilityState === 'visible') dispatch(fetchMerchantReplies(caseId));
    };
    check();
    const timer = setInterval(check, REPLY_POLL_INTERVAL_MS);
    window.addEventListener('focus', check);
    document.addEventListener('visibilitychange', check);

    return () => {
      clearInterval(timer);
      window.removeEventListener('focus', check);
      document.removeEventListener('visibilitychange', check);
    };
  }, [dispatch, caseId, active]);
};


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default usePollMerchantReply;
