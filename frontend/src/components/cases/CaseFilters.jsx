// [10d] CaseFilters — store + status dropdowns above the case queue
// Controlled by the Cases page, which reloads the list when a filter changes.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { CASE_STATUS_LABELS } from '../../api/format';


// ═══════════════════════════════════════════════════════════════════
// 2. CaseFilters component
// ═══════════════════════════════════════════════════════════════════
// Props:
//   storeIds  the user's store grants (/auth/me store_ids) — the store options
//   filters   { store_id, status } — '' means "all"
//   onChange  called with the new filters object
const CaseFilters = ({ storeIds, filters, onChange }) => {
  // ── 2a. Handlers ────────────────────────────────────────────────
  // One handler for both dropdowns: the <select> name is the filter key
  const handleChange = (e) => {
    onChange({ ...filters, [e.target.name]: e.target.value });
  };

  // ── 2b. Render ──────────────────────────────────────────────────
  return (
    <div className='filters'>
      <label>
        Store
        <select name='store_id' value={filters.store_id} onChange={handleChange}>
          <option value=''>All my stores</option>
          {storeIds.map((storeId) => (
            <option key={storeId} value={storeId}>{storeId}</option>
          ))}
        </select>
      </label>

      <label>
        Status
        <select name='status' value={filters.status} onChange={handleChange}>
          <option value=''>All statuses</option>
          {Object.entries(CASE_STATUS_LABELS).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
      </label>
    </div>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default CaseFilters;
