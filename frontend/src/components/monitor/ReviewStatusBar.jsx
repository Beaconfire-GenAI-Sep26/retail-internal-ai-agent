// [14f] ReviewStatusBar — how the store's claims were reviewed (D-06)
// One 100% bar per store: store fault · not store fault · fraud · pending.
// All claims, not only attributable ones, so the analyst sees what the M&I
// rate leaves out. Segment text shows when it fits; the <title> always has it.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports + segment order
// ═══════════════════════════════════════════════════════════════════
import { REVIEW_LABEL_LABELS, labelOf } from '../../api/format';

// Fixed order and colors (CSS classes in index.css section 15)
const REVIEW_ORDER = ['store_fault', 'not_store_fault', 'fraud', 'pending'];


// ═══════════════════════════════════════════════════════════════════
// 2. ReviewStatusBar component
// ═══════════════════════════════════════════════════════════════════
// Props:
//   stores  [{ storeId, counts: { review_label: n } }]
const ReviewStatusBar = ({ stores }) => (
  <div className='review-bars'>
    {stores.map((s) => {
      const total = REVIEW_ORDER.reduce((sum, k) => sum + (s.counts[k] ?? 0), 0);
      return (
        <div key={s.storeId} className='review-row'>
          <span className='review-store'>{s.storeId}</span>
          <div className='review-track'>
            {total === 0 && <span className='muted'>No claims</span>}
            {REVIEW_ORDER.map((k) => {
              const n = s.counts[k] ?? 0;
              if (!n) return null;
              const share = n / total;
              const text = `${labelOf(REVIEW_LABEL_LABELS, k)} ${n}`;
              return (
                <div key={k} className={`review-seg review-${k}`} style={{ flexGrow: share }}
                  title={`${text} (${Math.round(share * 100)}%)`}>
                  {share >= 0.12 && text}
                </div>
              );
            })}
          </div>
        </div>
      );
    })}
  </div>
);


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default ReviewStatusBar;
