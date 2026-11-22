// [11a] Pill — a small colored tag: confidence, hypothesis status, check kind, evidence type ...
// StatusBadge stays for case_status; Pill is for everything else, colored by meaning
// rather than by one enum. Colors live in index.css section 8 (.pill-ok, .pill-warn, ...).
//
//   <Pill tone='ok'>Supported</Pill>
//   tone: 'ok' (good / confirmed) · 'warn' (watch out) · 'bad' (failed / ruled against)
//         'accent' (in progress / highlighted, blue) · 'agent' (the agent said it, purple)
//         'ghost' (no longer counts, outline only) · 'neutral' (default)


// ═══════════════════════════════════════════════════════════════════
// 1. Pill component
// ═══════════════════════════════════════════════════════════════════
const Pill = ({ tone = 'neutral', children, title }) => (
  <span className={`pill pill-${tone}`} title={title}>{children}</span>
);


// ═══════════════════════════════════════════════════════════════════
// 2. Export
// ═══════════════════════════════════════════════════════════════════
export default Pill;
