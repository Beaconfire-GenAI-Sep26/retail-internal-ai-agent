// [11d] useElementWidth — the live pixel width of an element (D-06)
// Charts on the Monitor page draw in real pixels instead of scaling a fixed
// viewBox, so their text stays the same size on a phone and a wide screen.
// Usage: const [ref, width] = useElementWidth(); <div ref={ref}>…</div>


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useCallback, useRef, useState } from 'react';


// ═══════════════════════════════════════════════════════════════════
// 2. Hook
// ═══════════════════════════════════════════════════════════════════
// A callback ref, so it also works when the element mounts after a loading
// state. Without ResizeObserver (jsdom in tests) the width is read once.
const useElementWidth = (fallback = 640) => {
  const [width, setWidth] = useState(fallback);
  const observer = useRef(null);

  const ref = useCallback((node) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!node) return;
    if (node.clientWidth) setWidth(node.clientWidth);
    if (typeof ResizeObserver === 'undefined') return;
    observer.current = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)));
    observer.current.observe(node);
  }, []);

  return [ref, width];
};


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default useElementWidth;
