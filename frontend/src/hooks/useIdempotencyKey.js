// [08e] useIdempotencyKey — one Idempotency-Key per analyst action
// contracts.md "Idempotency": a repeat with a key already seen returns the first
// result and changes nothing. Sent on decision, reply, resume and recheck run.
//
// When to reuse the key (d03 plan, Commit 3):
//   - The request got NO response (network error, timeout): the server may have
//     done it. Trying the same action again reuses the key, so it can't happen twice.
//   - The request got an error RESPONSE (e.g. 502 DISPATCH_FAILED): the server
//     answered, so "Approve again" is a new action with a new key. Reusing it
//     could make a real backend replay the stored failure.
//   - A different action (Approve after a failed Reject): always a new key.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { useCallback, useRef } from 'react';


// ═══════════════════════════════════════════════════════════════════
// 2. Pure helpers (tested in useIdempotencyKey.test.js)
// ═══════════════════════════════════════════════════════════════════
// crypto.randomUUID needs a secure context (https or localhost). Opening the dev
// server by LAN IP isn't one, so fall back to a v4 UUID from getRandomValues.
export const newKey = () => {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const b = globalThis.crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const hex = [...b].map((x) => x.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
};

// last: { action, key, noResponse } from the previous attempt, or null
// action: what the analyst clicks now, e.g. 'approve'
export const keyFor = (last, action) =>
  last && last.noResponse && last.action === action ? last.key : newKey();


// ═══════════════════════════════════════════════════════════════════
// 3. Hook
// ═══════════════════════════════════════════════════════════════════
// const { keyFor, settle } = useIdempotencyKey();
//   const key = keyFor('approve');            // before sending
//   settle({ noResponse: true });             // after it fails with no response
//   settle(null);                             // after success or an error response
const useIdempotencyKey = () => {
  const last = useRef(null); // { action, key, noResponse }

  const getKey = useCallback((action) => {
    const key = keyFor(last.current, action);
    last.current = { action, key, noResponse: false };
    return key;
  }, []);

  // Only "no response" keeps the key for the next try of the same action
  const settle = useCallback((outcome) => {
    if (outcome?.noResponse && last.current) last.current.noResponse = true;
    else last.current = null;
  }, []);

  return { keyFor: getKey, settle };
};


// ═══════════════════════════════════════════════════════════════════
// 4. Export
// ═══════════════════════════════════════════════════════════════════
export default useIdempotencyKey;
