// [09e] useDocumentTitle — the browser tab names the page (D-06)
//   useDocumentTitle('CASE-0001')  →  "CASE-0001 · M&I Diagnosis"
// Several tabs open during a demo can be told apart. Every page calls it, so
// the title always matches the current page; no clean-up needed.

import { useEffect } from 'react';

export const APP_TITLE = 'M&I Diagnosis';

const useDocumentTitle = (title) => {
  useEffect(() => {
    document.title = title ? `${title} · ${APP_TITLE}` : APP_TITLE;
  }, [title]);
};

export default useDocumentTitle;
