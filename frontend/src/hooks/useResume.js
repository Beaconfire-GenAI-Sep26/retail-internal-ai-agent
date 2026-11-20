// [08f] useResume — the second call of "decide first, then resume" (D-05)
// Used after a question decision (QuestionReview) and a merchant reply
// (MerchantReplyForm), and by their "Continue" button when only the resume failed.
//
//   const { resume, resuming, error } = useResume(investigationId);
//   await resume();   // → true when the run continued
//
// One Idempotency-Key per try; the same key again only after no response
// (hooks/useIdempotencyKey.js).


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useCallback } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { resumeInvestigation } from '../store/investigations/investigationsThunks';
import { selectResumeStatus, selectResumeError } from '../store/investigations/investigationsSelectors';
import useIdempotencyKey from './useIdempotencyKey';


// ═══════════════════════════════════════════════════════════════════
// 2. Hook
// ═══════════════════════════════════════════════════════════════════
const useResume = (investigationId) => {
  const dispatch = useDispatch();
  const status = useSelector(selectResumeStatus);
  const error = useSelector(selectResumeError);
  const { keyFor, settle } = useIdempotencyKey();

  const resume = useCallback(async () => {
    const result = await dispatch(resumeInvestigation({ id: investigationId, idempotencyKey: keyFor('resume') }));
    const ok = resumeInvestigation.fulfilled.match(result);
    settle(ok ? null : result.payload);
    return ok;
  }, [dispatch, investigationId, keyFor, settle]);

  return { resume, resuming: status === 'loading', error: status === 'failed' ? error : null };
};


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default useResume;
