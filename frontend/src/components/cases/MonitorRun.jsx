// [10f] MonitorRun — "Run monitor" button + a one-line result (analyst only)
// POST /domain/monitor/run opens a case for each store over the threshold.
// The page decides who sees this; the backend answers 403 for viewers anyway.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useEffect, useRef, useState } from 'react';
import { useDispatch } from 'react-redux';
import { runMonitor } from '../../store/cases/casesThunks';


// ═══════════════════════════════════════════════════════════════════
// 2. Result text
// ═══════════════════════════════════════════════════════════════════
// SkippedStore.reason → what it means for the analyst: [one store, several stores]
const SKIP_LABELS = {
  open_case_exists: ['already has an open case', 'already have an open case'],
  already_reviewed: ['was already reviewed', 'were already reviewed'], // a closed case covers this window (PR #31)
  below_threshold: ['is within the goal', 'are within the goal'],
  low_volume: ['has too few orders', 'have too few orders'],
};

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

// MonitorRunResponse → a short line by the button, and the detail for the
// "Details" bubble (with every granted store, IDs and counts are too long to show):
//   short   "Opened 7 cases."  ·  "Opened 1 case."  ·  "No new cases."
//   detail  ["Opened: CASE-0008, CASE-0009", "6 stores already have an open case", "1 store was already reviewed", …]
const describeRun = (run) => {
  const opened = run.opened_case_ids;
  const short = opened.length === 0 ? 'No new cases.' : `Opened ${plural(opened.length, 'case')}.`;

  // The new case IDs, then the skipped stores counted per reason (order of SKIP_LABELS)
  const detail = opened.length > 0 ? [`Opened: ${opened.join(', ')}`] : [];
  for (const [reason, [one, many]] of Object.entries(SKIP_LABELS)) {
    const n = run.skipped.filter((s) => s.reason === reason).length;
    if (n > 0) detail.push(`${plural(n, 'store')} ${n === 1 ? one : many}`);
  }
  return { short, detail };
};


// ═══════════════════════════════════════════════════════════════════
// 3. MonitorRun component
// ═══════════════════════════════════════════════════════════════════
// onDone: called after a successful run, so the page can reload the queue
const MonitorRun = ({ onDone }) => {
  const dispatch = useDispatch();
  // Local: only this button cares, and it shouldn't outlive the page
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null); // { ok, text, detail? }
  const [showDetail, setShowDetail] = useState(false);
  const rootRef = useRef(null);

  // The bubble closes on a click outside it, or on Escape
  useEffect(() => {
    if (!showDetail) return undefined;
    const onPointer = (e) => {
      if (!rootRef.current?.contains(e.target)) setShowDetail(false);
    };
    const onKey = (e) => {
      if (e.key === 'Escape') setShowDetail(false);
    };
    document.addEventListener('pointerdown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [showDetail]);

  const handleClick = async () => {
    setRunning(true);
    setResult(null);
    setShowDetail(false);
    try {
      const run = await dispatch(runMonitor()).unwrap();
      const { short, detail } = describeRun(run);
      setResult({ ok: true, text: short, detail });
      onDone();
    } catch (message) {
      setResult({ ok: false, text: message });
    } finally {
      setRunning(false);
    }
  };

  // The button comes first in the DOM (tab order); CSS puts the result on its
  // left, so a longer result never moves the button. "Details" opens a small
  // bubble under it that floats over the page, so nothing below moves either.
  const hasDetail = result?.ok && result.detail.length > 0;
  return (
    <div className='monitor-run' ref={rootRef}>
      <button type='button' onClick={handleClick} disabled={running}>
        {running ? 'Running…' : 'Run monitor'}
      </button>
      {result && (
        <p className={result.ok ? 'muted' : 'error'} role={result.ok ? 'status' : 'alert'}>
          {result.text}
          {hasDetail && (
            <>
              {' '}
              <button
                type='button'
                className='evidence-more'
                onClick={() => setShowDetail(!showDetail)}
                aria-expanded={showDetail}
                aria-controls='monitor-run-detail'
              >
                Details
              </button>
            </>
          )}
        </p>
      )}
      {hasDetail && showDetail && (
        <div className='monitor-run-bubble' id='monitor-run-detail' role='dialog' aria-label='Monitor run details'>
          <ul>
            {result.detail.map((line) => <li key={line}>{line}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 4. Export
// ═══════════════════════════════════════════════════════════════════
export default MonitorRun;
