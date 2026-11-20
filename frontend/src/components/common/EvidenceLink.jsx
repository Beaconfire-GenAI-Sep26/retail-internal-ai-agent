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
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default EvidenceLink;
