// When an Idempotency-Key is reused, and when a new one is made
import { describe, expect, it } from 'vitest';
import { keyFor, newKey } from './useIdempotencyKey';

describe('keyFor', () => {
  it('first click → a new UUID', () => {
    expect(keyFor(null, 'approve')).toMatch(/^[0-9a-f-]{36}$/);
  });

  it('same action again after NO response → the same key', () => {
    expect(keyFor({ action: 'approve', key: 'k1', noResponse: true }, 'approve')).toBe('k1');
  });

  it('after an error RESPONSE (e.g. DISPATCH_FAILED) → a new key', () => {
    expect(keyFor({ action: 'approve', key: 'k1', noResponse: false }, 'approve')).not.toBe('k1');
  });

  it('a different action → a new key, even after no response', () => {
    expect(keyFor({ action: 'reject', key: 'k1', noResponse: true }, 'approve')).not.toBe('k1');
  });

  it('two new keys differ', () => {
    expect(newKey()).not.toBe(newKey());
  });
});
