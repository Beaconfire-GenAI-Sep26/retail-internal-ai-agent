// [10c] StatusBadge — a case_status shown as a colored tag
// Used by the case queue and the case header. The color per status lives in
// index.css section 5 (.badge-open, .badge-investigating, ...).


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { CASE_STATUS_LABELS } from '../api/format';


// ═══════════════════════════════════════════════════════════════════
// 2. StatusBadge component
// ═══════════════════════════════════════════════════════════════════
// status: contract case_status, e.g. 'open' → <span class="badge badge-open">Open</span>
// An unknown value still shows (as the raw value) instead of disappearing.
const StatusBadge = ({ status }) => (
  <span className={`badge badge-${status}`}>{CASE_STATUS_LABELS[status] ?? status}</span>
);


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default StatusBadge;
