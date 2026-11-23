// [11b] EvidenceLink — an evidence ID as a button that opens the evidence drawer
// Used wherever the result, a check or a proposal cites evidence:
//   <EvidenceLink id='EV-CLM-004410' />
// It only sets state.evidence.openId; EvidenceDrawer (on the case page) fetches
// and shows the record.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useState } from 'react';
import { useDispatch } from 'react-redux';
import { openEvidence } from '../../store/evidence/evidenceSlice';


// ═══════════════════════════════════════════════════════════════════
// 2. EvidenceLink component
// ═══════════════════════════════════════════════════════════════════
// id: the evidence ID · children: optional text instead of the ID
// tone: 'support' (green dot) · 'against' (red dot) · none (grey dot)
const EvidenceLink = ({ id, tone, children }) => {
  const dispatch = useDispatch();

  return (
    <button
      type='button'
      className={`evidence-link${tone ? ` evidence-${tone}` : ''}`}
      onClick={() => dispatch(openEvidence(id))}
      aria-haspopup='dialog'
      title={`Open evidence ${id}`}
    >
      {children ?? id}
    </button>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 3. EvidenceLinks — a labelled row of evidence IDs, nothing if the list is empty
// ═══════════════════════════════════════════════════════════════════
//   <EvidenceLinks label='Supports' ids={hypothesis.supporting_evidence_ids} />
//   → Supports: EV-EVT-000031 · EV-CLM-004410
// limit (optional): show the first `limit` IDs, fold the rest behind "+N more"
//   <EvidenceLinks label='Evidence' ids={check.evidence_ids} limit={3} />
//   → Evidence: EV-CLM-1 · EV-CLM-2 · EV-CLM-3  +9 more
// tone (optional): passed to each chip — 'support' or 'against'
export const EvidenceLinks = ({ label, ids, limit, tone }) => {
  const [expanded, setExpanded] = useState(false);
  if (!ids?.length) return null;

  // Folding one ID saves nothing, so fold only when 2+ would be hidden
  const foldable = limit != null && ids.length > limit + 1;
  const shown = foldable && !expanded ? ids.slice(0, limit) : ids;

  return (
    <p className='evidence-links'>
      {label && <span className='muted'>{label}: </span>}
      {shown.map((id) => <EvidenceLink key={id} id={id} tone={tone} />)}
      {foldable && (
        <button type='button' className='evidence-more' onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>
          {expanded ? 'Show less' : `+${ids.length - limit} more`}
        </button>
      )}
    </p>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 4. Export
// ═══════════════════════════════════════════════════════════════════
export default EvidenceLink;
