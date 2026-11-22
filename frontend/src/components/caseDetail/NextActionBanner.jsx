// [10w] NextActionBanner — top of the case page: "it's your turn, and here's what to do"
//   (!)  Your decision is needed                                [Review action ↓]
//        The agent recommends an action. Nothing is sent until you approve it.
// Shown only to analysts, only when the case waits for them (caseStages.js
// getNextAction). The button jumps to the investigation, where the action is.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useSelector } from 'react-redux';
import { selectIsAnalyst } from '../../store/auth/authSelectors';
import { getNextAction } from './caseStages';


// ═══════════════════════════════════════════════════════════════════
// 2. NextActionBanner component
// ═══════════════════════════════════════════════════════════════════
// view: getCaseView(...), or null · target: the anchor id to jump to
const NextActionBanner = ({ view, caseDetail, target }) => {
  const isAnalyst = useSelector(selectIsAnalyst);
  const next = getNextAction({ view, caseDetail, isAnalyst });
  if (!next) return null;

  return (
    <div className='next-action' role='status'>
      <span className='next-action-icon' aria-hidden='true'>
        <svg viewBox='0 0 24 24' fill='none' stroke='currentColor' strokeWidth='2.4' strokeLinecap='round'>
          <circle cx='12' cy='12' r='9' />
          <path d='M12 7.5v5.5M12 16.5v.5' />
        </svg>
      </span>
      <div className='next-action-text'>
        <strong>{next.title}</strong>
        <span>{next.text}</span>
      </div>
      <a className='next-action-cta' href={`#${target}`}>{next.cta} ↓</a>
    </div>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default NextActionBanner;
