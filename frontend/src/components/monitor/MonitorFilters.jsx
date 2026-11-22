// [14g] MonitorFilters — which stores and which days the dashboard shows (D-06)
//   Stores  "Compare all" (only with 2+ store grants) · one button per store
//   Range   last 42 / 14 / 7 days, ending on the last day of data
// Segmented buttons with aria-pressed, so screen readers hear the current choice.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { ALL_STORES, RANGE_OPTIONS } from './monitorMath';


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
//   store     ALL_STORES or a store ID
//   range     days (one of RANGE_OPTIONS)
//   onChange  ({ store?, range? }) → void
const MonitorFilters = ({ storeIds, store, range, onChange }) => {
  const storeOptions = [
    ...(storeIds.length > 1 ? [{ value: ALL_STORES, label: 'Compare all' }] : []),
    ...storeIds.map((id) => ({ value: id, label: id })),
  ];
  const rangeOptions = RANGE_OPTIONS.map((d) => ({ value: d, label: `Last ${d} days` }));

  return (
    <div className='monitor-filters'>
      <Segmented label='Stores' options={storeOptions} value={store} onChange={(v) => onChange({ store: v })} />
      <Segmented label='Time range' options={rangeOptions} value={range} onChange={(v) => onChange({ range: v })} />
    </div>
  );
};


// ═══════════════════════════════════════════════════════════════════
// 4. Export
// ═══════════════════════════════════════════════════════════════════
export default MonitorFilters;
