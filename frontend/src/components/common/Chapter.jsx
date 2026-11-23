// [11c] Chapter — a numbered section title that groups the case page into a story
//   ① WHAT HAPPENED ──────────────────────────── store data
// The page reads top to bottom: what happened → what the agent found → your
// decision → how the agent got there. Each part starts with one of these.
//
//   <Chapter title='What happened' meta='Store data' />
//   The number is a CSS counter (index.css section 6), so chapters that show
//   only sometimes (the action, the recheck, the merchant conversation) never
//   leave a gap or a repeat.
//   tone='brand' (red) marks the chapter where the analyst has to act.
//   id: an anchor the next-action banner can jump to.


// ═══════════════════════════════════════════════════════════════════
// 1. Chapter component
// ═══════════════════════════════════════════════════════════════════
const Chapter = ({ title, meta, tone, id }) => (
  <div className={`chapter${tone ? ` chapter-${tone}` : ''}`} id={id}>
    <span className='chapter-number' aria-hidden='true' />
    <h2>{title}</h2>
    <span className='chapter-rule' aria-hidden='true' />
    {meta && <span className='chapter-meta'>{meta}</span>}
  </div>
);


// ═══════════════════════════════════════════════════════════════════
// 2. Export
// ═══════════════════════════════════════════════════════════════════
export default Chapter;
