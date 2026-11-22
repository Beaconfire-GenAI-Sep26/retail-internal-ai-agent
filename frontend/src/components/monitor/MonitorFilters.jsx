// [14g] MonitorFilters — which store and which days the dashboard shows (D-06)
//   Store   dropdown of the user's store grants, one store at a time
//           (a dropdown, not buttons, so it still fits with many stores)
//   Range   last 42 / 14 / 7 days, ending on the last day of data
// Range is segmented buttons with aria-pressed, so screen readers hear the current choice.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { RANGE_OPTIONS } from './monitorMath';


// ═══════════════════════════════════════════════════════════════════
// 2. Segmented control
// ═══════════════════════════════════════════════════════════════════
// options: [{ value, label }]
export const Segmented = ({ label, options, value, onChange }) => (
  <div className='segmented' role='group' aria-label={label}>
    {options.map((o) => (
      <button key={o.value} type='button' aria-pressed={o.value === value} onClick={() => onChange(o.value)}>
        {o.label}
      </button>
    ))}
  </div>
);


// ═══════════════════════════════════════════════════════════════════
// 3. MonitorFilters component
// ═══════════════════════════════════════════════════════════════════
// Props:
//   storeIds  the user's store grants (/auth/me store_ids)
//   store     the store ID shown
//   range     days (one of RANGE_OPTIONS)
//   onChange  ({ store?, range? }) → void
const MonitorFilters = ({ storeIds, store, range, onChange }) => {
  const rangeOptions = RANGE_OPTIONS.map((d) => ({ value: d, label: `Last ${d} days` }));

  return (
    <div className='monitor-filters'>
      <label className='monitor-store'>
        Store
        <select value={store} onChange={(e) => onChange({ store: e.target.value })}>
          {storeIds.map((id) => <option key={id} value={id}>{id}</option>)}
        </select>
      </label>
      <Segmented label='Time range' options={rangeOptions} value={range} onChange={(v) => onChange({ range: v })} />
    </div>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 4. Export
// ═══════════════════════════════════════════════════════════════════
export default MonitorFilters;
