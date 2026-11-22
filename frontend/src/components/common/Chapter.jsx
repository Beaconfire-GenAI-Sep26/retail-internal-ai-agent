// [11c] Chapter — a numbered section title that groups the case page into a story
//   ① WHAT HAPPENED ──────────────────────────── store data
// The page reads top to bottom: what happened → what the agent found → your
// decision → how the agent got there. Each part starts with one of these.
//
//   <Chapter number={1} title='What happened' meta='Store data' />
//   tone='brand' (red) marks the chapter where the analyst has to act.
//   id: an anchor the next-action banner can jump to.


// ═══════════════════════════════════════════════════════════════════
// 1. Chapter component
// ═══════════════════════════════════════════════════════════════════
const Chapter = ({ number, title, meta, tone, id }) => (
  <div className={`chapter${tone ? ` chapter-${tone}` : ''}`} id={id}>
    <span className='chapter-number' aria-hidden='true'>{number}</span>
    <h2>{title}</h2>
    <span className='chapter-rule' aria-hidden='true' />
    {meta && <span className='chapter-meta'>{meta}</span>}
  </div>
);


// ═══════════════════════════════════════════════════════════════════
// 2. Export
// ═══════════════════════════════════════════════════════════════════
export default Chapter;
