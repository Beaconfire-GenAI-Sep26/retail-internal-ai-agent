// [11b] EvidenceLink — an evidence ID as a button that opens the evidence drawer
// Used wherever the result, a check or a proposal cites evidence:
//   <EvidenceLink id='EV-CLM-004410' />
// It only sets state.evidence.openId; EvidenceDrawer (on the case page) fetches
// and shows the record.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useDispatch } from 'react-redux';
import { openEvidence } from '../../store/evidence/evidenceSlice';


// ═══════════════════════════════════════════════════════════════════
// 2. EvidenceLink component
// ═══════════════════════════════════════════════════════════════════
// id: the evidence ID · children: optional text instead of the ID
const EvidenceLink = ({ id, children }) => {
  const dispatch = useDispatch();

  return (
    <button
      type='button'
      className='evidence-link'
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
export const EvidenceLinks = ({ label, ids }) => {
  if (!ids?.length) return null;
  return (
    <p className='evidence-links'>
      {label && <span className='muted'>{label}: </span>}
      {ids.map((id) => <EvidenceLink key={id} id={id} />)}
    </p>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 4. Export
// ═══════════════════════════════════════════════════════════════════
export default EvidenceLink;
