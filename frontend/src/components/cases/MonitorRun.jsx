// [10f] MonitorRun — "Run monitor" button + a one-line result (analyst only)
// POST /domain/monitor/run opens a case for each store over the threshold.
// The page decides who sees this; the backend answers 403 for viewers anyway.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useState } from 'react';
import { useDispatch } from 'react-redux';
import { runMonitor } from '../../store/cases/casesThunks';


// ═══════════════════════════════════════════════════════════════════
// 2. Result text
// ═══════════════════════════════════════════════════════════════════
// SkippedStore.reason → what it means for the analyst
const SKIP_LABELS = {
  open_case_exists: 'already have an open case',
  below_threshold: 'are within the goal',
  low_volume: 'have too few orders',
};

// MonitorRunResponse → e.g.
// "Opened 2 cases: CASE-1, CASE-2. 6 stores are within the goal."
const describeRun = (run) => {
  const opened = run.opened_case_ids;
  const parts = [
    opened.length === 0
      ? 'No new cases.'
      : `Opened ${opened.length} ${opened.length === 1 ? 'case' : 'cases'}: ${opened.join(', ')}.`,
  ];

  // Count skipped stores per reason, in the order of SKIP_LABELS
  for (const [reason, label] of Object.entries(SKIP_LABELS)) {
    const n = run.skipped.filter((s) => s.reason === reason).length;
    if (n > 0) parts.push(`${n} ${n === 1 ? 'store' : 'stores'} ${label}.`);
  }
  return parts.join(' ');
};


// ═══════════════════════════════════════════════════════════════════
// 3. MonitorRun component
// ═══════════════════════════════════════════════════════════════════
// onDone: called after a successful run, so the page can reload the queue
const MonitorRun = ({ onDone }) => {
  const dispatch = useDispatch();
  // Local: only this button cares, and it shouldn't outlive the page
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null); // { ok, text }

  const handleClick = async () => {
    setRunning(true);
    setResult(null);
    try {
      const run = await dispatch(runMonitor()).unwrap();
      setResult({ ok: true, text: describeRun(run) });
      onDone();
    } catch (message) {
      setResult({ ok: false, text: message });
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className='monitor-run'>
      <button type='button' onClick={handleClick} disabled={running}>
        {running ? 'Running…' : 'Run monitor'}
      </button>
      {result && (
        <p className={result.ok ? 'muted' : 'error'} role={result.ok ? 'status' : 'alert'}>
          {result.text}
        </p>
      )}
    </div>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 4. Export
// ═══════════════════════════════════════════════════════════════════
export default MonitorRun;
