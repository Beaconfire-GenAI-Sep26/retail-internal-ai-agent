// [14e] TopItems — the menu items with the most attributable claims (D-06)
// One small table per store: item · claims · claim rate (claims / delivered
// orders that had the item). Below it, the modifier with the most claims —
// Domain can't group by item and modifier at once, so it is its own line.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { formatRate, formatRatio } from '../../api/format';
import { rate } from './monitorMath';

const TOP_N = 5;


// ═══════════════════════════════════════════════════════════════════
// 2. TopItems component
// ═══════════════════════════════════════════════════════════════════
// Props:
//   stores  [{ storeId, color, items, modifiers, itemNames }]
//           items / modifiers: [{ key, claims, orders }] from claim_breakdown
//           itemNames: { item_id: name } from the menu
// Claims with no item_id ("unknown", e.g. whole-order claims) are left out.
const TopItems = ({ stores }) => (
  <div className='top-items'>
    {stores.map((s) => {
      const top = s.items
        .filter((it) => it.key !== 'unknown' && it.claims > 0)
        .sort((a, b) => b.claims - a.claims)
        .slice(0, TOP_N);
      const topModifier = [...s.modifiers].sort((a, b) => b.claims - a.claims)[0];
      return (
        <div key={s.storeId}>
          <h3><span className='swatch' style={{ background: s.color }} />{s.storeId}</h3>
          {top.length === 0 ? (
            <p className='muted'>No attributable claims in this range.</p>
          ) : (
            <table>
              <thead>
                <tr><th>Item</th><th className='num'>Claims</th><th className='num'>Rate</th></tr>
              </thead>
              <tbody>
                {top.map((it) => (
                  <tr key={it.key}>
                    <td>{s.itemNames[it.key] ?? it.key}</td>
                    <td className='num'>{it.claims}</td>
                    <td className='num' title={it.orders ? formatRatio(it.claims, it.orders) : undefined}>
                      {formatRate(rate(it.claims, it.orders))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {topModifier?.claims > 0 && (
            <p className='top-modifier'>
              Top modifier: <span className='pill pill-bad'>{topModifier.key}</span>{' '}
              {topModifier.claims} claims · {formatRate(rate(topModifier.claims, topModifier.orders))} of orders with it
            </p>
          )}
        </div>
      );
    })}
  </div>
);


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default TopItems;
